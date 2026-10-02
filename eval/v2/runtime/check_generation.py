"""Paid Flash acceptance against the existing isolated synthetic dataset.

Run inside the acceptance API container against retrieval_report.json.
Credentials stay in memory. Writes synthetic evidence only to /tmp.
Holdout is opt-in and must not be used for tuning.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import UUID

import asyncpg
import httpx

sys.path.insert(0, '/app')

from app.core.config import get_settings
from app.services.auth import AccessTokenCodec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['tune', 'holdout'], default='tune')
    parser.add_argument('--label', default='baseline')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--binding', default='/runtime/retrieval_report.json')
    args = parser.parse_args()
    settings = get_settings()
    assert settings.deepseek_model == 'deepseek-flash'
    assert settings.deepseek_api_key and settings.deepseek_api_key.get_secret_value()
    binding = json.loads(Path(args.binding).read_text())
    assert binding['status'] == 'PASSED'
    sid = binding['space_id']
    output = Path('/tmp/flash-' + args.split + '-' + args.label + '.json')
    report = {'date': datetime.now(timezone.utc).isoformat(), 'model': settings.deepseek_model,
              'thinking_enabled': settings.deepseek_thinking_enabled, 'split': args.split,
              'label': args.label, 'space_id': sid, 'synthetic_sources_only': True,
              'human_review_performed': False, 'checks': []}

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    async def credential():
        dsn = str(settings.database_url).replace('postgresql+asyncpg://', 'postgresql://')
        assert dsn.endswith('/v2_acceptance'), 'Only the isolated database is allowed'
        db = await asyncpg.connect(dsn)
        try:
            row = await db.fetchrow('SELECT owner_user_id, name FROM knowledge_spaces WHERE id=$1', UUID(sid))
            assert row and row['name'].startswith('V2-isolated-')
            return AccessTokenCodec(secret=settings.auth_access_token_secret.get_secret_value(),
                                    ttl_seconds=3600).issue(row['owner_user_id'])
        finally:
            await db.close()

    def check(name, ok):
        assert ok, name
        report['checks'].append(name)
        save()
        print('PASS ' + name, flush=True)

    token = asyncio.run(credential())

    async def persisted_citations(message_id):
        db = await asyncpg.connect(str(settings.database_url).replace('postgresql+asyncpg://', 'postgresql://'))
        try:
            rows = await db.fetch('SELECT c.document_name, c.quoted_text, ch.document_id FROM citations c '
                                  'LEFT JOIN chunks ch ON ch.id=c.chunk_id WHERE c.message_id=$1', UUID(message_id))
            return [{'document_name': r['document_name'], 'quoted_text': r['quoted_text'],
                     'document_id': str(r['document_id']) if r['document_id'] else None} for r in rows]
        finally:
            await db.close()

    client = httpx.Client(base_url='http://127.0.0.1:8000/api/v1', timeout=700,
                         headers={'Authorization': 'Bearer ' + token})

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f'{method} {path}: HTTP {response.status_code}')
        return response.json() if response.content else None

    try:
        if args.smoke:
            conversation = request('POST', '/owner/conversations', json={'space_id': sid})
            answer = request('POST', f'/owner/conversations/{conversation["id"]}/messages',
                             json={'question': '试用期有多少天？'})
            report['owner_smoke'] = answer
            check('real_owner_flash_answer_with_citation', answer['status'] == 'ANSWERED'
                  and '14' in answer['answer'] and bool(answer['citations']) and 'flash' in answer['model'])
            link = request('POST', f'/spaces/{sid}/share-links',
                           json={'category_ids': [binding['category_ids']['open']]})
            try:
                public = request('POST', '/public/query', json={'token': link['token'], 'question': '试用期有多少天？'})
                report['public_smoke'] = public
                public_citations = asyncio.run(persisted_citations(public['message_id']))
                report['public_persisted_citations'] = public_citations
                check('real_public_flash_answer_with_citation', public['status'] == 'ANSWERED'
                      and '14' in public['answer'] and bool(public_citations))
                check('public_response_keeps_sources_private', set(public) == {'message_id', 'status', 'answer'})
                private = request('POST', '/public/query', json={'token': link['token'],
                                   'question': '内部报销的审核口令是什么？'})
                report['public_private_query'] = private
                private_citations = asyncio.run(persisted_citations(private['message_id']))
                report['public_private_query_persisted_citations'] = private_citations
                closed = [c for d in binding['documents'].values() if d['category_alias'] == 'closed'
                          for c in d['chunks']]
                assert closed, 'Private canary fixture must exist'
                check('public_private_source_not_cited', all(c.get('document_id') !=
                      d['document_id'] for c in private_citations for d in binding['documents'].values()
                      if d['category_alias'] == 'closed'))
                # Full private source text must never be present, even if the
                # model echoes the visitor's question.
                check('public_private_source_text_not_leaked',
                      'SYNTHETIC_PRIVATE_CANARY_9A7' not in private['answer']
                      and all(c['content'] not in private['answer'] for c in closed))
            finally:
                request('DELETE', '/share-links/' + link['link']['id'])
        vid = binding['version_ids'][args.split]
        version = request('GET', '/eval-versions/' + vid)
        expected = 35 if args.split == 'tune' else 15
        check('frozen_' + args.split + '_case_count', len(version['cases']) == expected)
        report['frozen_version'] = version
        submitted = request('POST', f'/eval-versions/{vid}/runs/async')
        report['run_id'] = submitted['id']
        save()
        deadline = time.monotonic() + 1800
        last = None
        while time.monotonic() < deadline:
            detail = request('GET', '/eval-runs/' + submitted['id'])
            report['detail'] = detail
            save()
            progress = (detail['run']['status'], detail['run']['progress_completed'])
            if progress != last:
                print(f'RUN {args.split} {progress[0]} {progress[1]}/{expected}', flush=True)
                last = progress
            if progress[0] in ('COMPLETED', 'FAILED'):
                break
            time.sleep(5)
        else:
            raise TimeoutError('Evaluation did not finish within 30 minutes')
        check('async_' + args.split + '_completed', detail['run']['status'] == 'COMPLETED'
              and len(detail['results']) == expected and detail['run']['progress_completed'] == expected)
        check('no_out_of_scope_citations', detail['summary']['out_of_scope_violations'] == 0)
        report['status'] = 'COMPLETED'
        # Quality failures are findings, not fabricated passes or a reason to
        # discard the completed run. Manual answer accuracy remains unscored.
        save()
        print('COMPLETED actual Flash run; human answer review remains pending', flush=True)
    except Exception as error:
        report['status'] = 'FAILED'
        report['failure'] = str(error)
        save()
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
