"""Real isolated API/worker/BGE/pgvector acceptance; never calls an LLM.

Run from repository root. Reports contain synthetic sources and IDs only;
credentials and public session cookies are never written or printed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:18000/api/v1')
    parser.add_argument('--output', default='eval/v2/runtime/retrieval_report.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    dataset_path = root / 'eval/v2/gold_cases.json'
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    report = {'date': datetime.now(timezone.utc).isoformat(), 'mode': 'real_isolated_api_worker_bge_pgvector_no_llm',
              'dataset_sha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
              'holdout_evaluated': False, 'llm_calls': 0, 'checks': [], 'documents': {}, 'retrievals': []}
    output = root / args.output
    client = httpx.Client(base_url=args.base, timeout=700)

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(name, condition):
        assert condition, name
        report['checks'].append(name)
        save()
        print('PASS ' + name, flush=True)

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            # Do not print response bodies from authentication endpoints.
            raise RuntimeError(f'{method} {path}: HTTP {response.status_code}')
        return response.json() if response.content else None

    def wait_ready(doc_id, expected_version=None):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            value = request('GET', f'/documents/{doc_id}')
            if value['status'] == 'FAILED':
                raise RuntimeError('Synthetic document ingestion failed: ' + str(value['failure_code']))
            if value['status'] == 'READY' and (expected_version is None or value['active_version_id'] == expected_version):
                return value
            time.sleep(2)
        raise TimeoutError('Synthetic document ingestion did not complete')

    try:
        auth = request('POST', '/auth/register', json={'email': 'v2-' + uuid.uuid4().hex + '@example.test',
                   'password': secrets.token_urlsafe(24), 'display_name': 'V2 隔离验收'})
        client.headers['Authorization'] = 'Bearer ' + auth['tokens']['access_token']
        space = request('POST', '/spaces', json={'name': 'V2-isolated-' + uuid.uuid4().hex[:8],
                     'description': 'Synthetic acceptance data only', 'visibility': 'PUBLIC'})
        sid = space['id']
        report['space_id'] = sid
        request('PATCH', f'/spaces/{sid}', json={'plan': 'PRO'})
        categories = {}
        for alias in ('open', 'conflict', 'closed'):
            categories[alias] = request('POST', f'/spaces/{sid}/categories',
                    json={'name': alias, 'is_open': alias == 'open'})['id']
        report['category_ids'] = categories
        for source in sorted((dataset_path.parent / 'sources').glob('*.txt')):
            alias = 'open' if source.name[:2].isdigit() else 'conflict' if 'conflict' in source.name else 'closed'
            submitted = request('POST', f'/spaces/{sid}/documents',
                files={'file': (source.name, source.read_bytes(), 'text/plain')}, data={'category_id': categories[alias]})
            doc = wait_ready(submitted['document']['id'])
            detail = request('GET', f'/owner/spaces/{sid}/documents/{doc["id"]}')
            check('real_ingestion:' + source.name, bool(detail['chunks']) and all(c['token_count'] > 0 for c in detail['chunks']))
            report['documents'][source.name] = {'document_id': doc['id'], 'version_id': doc['active_version_id'],
                                              'category_alias': alias, 'chunks': detail['chunks']}
            save()
        check('23_sources_ingested', len(report['documents']) == 23)

        bound = {'tune': [], 'holdout': []}
        for case in dataset['cases']:
            refs = []
            for template in case['evidence_templates']:
                doc = report['documents'][template['filename']]
                chunk = next(c for c in doc['chunks'] if c['source_block_id'] == template['source_block_id'] and
                             c['char_start'] <= template['char_start'] and c['char_end'] >= template['char_end'])
                text = chunk['content'][template['char_start'] - chunk['char_start']:template['char_end'] - chunk['char_start']]
                assert hashlib.sha256(text.encode()).hexdigest() == template['text_hash'], 'actual source hash differs'
                refs.append({'document_id': doc['document_id'], 'document_version_id': doc['version_id'],
                             **{k: template[k] for k in ('source_block_id', 'char_start', 'char_end', 'text_hash', 'required')}})
            created = request('POST', f'/spaces/{sid}/eval-cases', json={
                'question': case['question'], 'expected_answer': case['expected_answer'], 'scope': case['scope'],
                'category_ids': [categories[a] for a in case['category_aliases']], 'answerable': case['answerable'],
                'expected_behavior': case['expected_behavior'], 'evidence_refs': refs,
                'expected_document_ids': list(dict.fromkeys(r['document_id'] for r in refs))})
            bound[case['split']].append(created['id'])
            # Owner endpoint intentionally measures owner scope only. Public
            # scope needs separate tests; do not apply owner results to it.
            if case['split'] == 'tune' and case['scope'] == 'OWNER':
                run = request('POST', f'/owner/spaces/{sid}/retrieval-runs', json={'question': case['question'], 'top_k': 5})
                expected = set(r['document_id'] for r in refs)
                found = set(item['document_id'] for item in run['items'])
                report['retrievals'].append({'case_id': case['id'], 'run_id': run['run_id'], 'scope': 'OWNER',
                    'items': run['items'], 'timings_ms': run['timings_ms'],
                    'document_recall_at_5': len(expected & found) / len(expected) if expected else None})
                if expected:
                    assert expected & found, 'No expected document in real Top K'
        for split, expected_count in [('tune', 35), ('holdout', 15)]:
            version = request('POST', f'/spaces/{sid}/eval-versions', json={'label': 'V2-' + split, 'case_ids': bound[split]})
            check('frozen_version:' + split, len(version['cases']) == expected_count)
            report.setdefault('version_ids', {})[split] = version['id']
        report['case_ids'] = bound
        check('50_cases_bound_to_actual_evidence', sum(map(len, bound.values())) == 50)

        first_doc = report['documents']['01-试用期.txt']['document_id']
        first_run = report['retrievals'][0]['run_id']
        check('saved_retrieval', bool(request('GET', f'/owner/retrieval-runs/{first_run}')['items']))
        outsider = httpx.Client(base_url=args.base, timeout=30)
        other_auth = outsider.post('/auth/register', json={'email': 'outsider-' + uuid.uuid4().hex + '@example.test',
                    'password': secrets.token_urlsafe(24), 'display_name': '隔离权限验收'}).json()
        outsider.headers['Authorization'] = 'Bearer ' + other_auth['tokens']['access_token']
        check('cross_owner_retrieval_denied', outsider.post(f'/owner/spaces/{sid}/retrieval-runs',
              json={'question': '试用期', 'top_k': 5}).status_code in (403, 404))
        check('cross_owner_document_denied', outsider.get(f'/owner/spaces/{sid}/documents/{first_doc}').status_code in (403, 404))
        check('cross_owner_history_denied', outsider.get(f'/owner/retrieval-runs/{first_run}').status_code in (403, 404))
        outsider.close()
        check('public_cannot_call_owner_diagnostics', httpx.post(args.base + f'/owner/spaces/{sid}/retrieval-runs',
                      json={'question': '试用期', 'top_k': 5}).status_code == 401)

        link = request('POST', f'/spaces/{sid}/share-links', json={'category_ids': [categories['open']]})
        visitor = httpx.Client(base_url=args.base, timeout=60)
        session = visitor.post('/public/session', json={'token': link['token']})
        check('real_public_session', session.status_code == 200)
        public_space = visitor.get('/public/space').json()
        check('public_only_open_category', [c['name'] for c in public_space['categories']] == ['open'])
        request('PATCH', '/categories/' + categories['open'], json={'is_open': False})
        closed = visitor.get('/public/space')
        check('public_closed_category_denied', closed.status_code in (401, 403, 404) or closed.json().get('categories') == [])
        request('DELETE', '/share-links/' + link['link']['id'])
        check('public_revoked_session_denied', visitor.get('/public/space').status_code in (401, 403, 404))
        request('PATCH', '/categories/' + categories['open'], json={'is_open': True})
        visitor.close()

        request('PATCH', '/documents/' + first_doc + '/availability', json={'is_enabled': False})
        run = request('POST', f'/owner/spaces/{sid}/retrieval-runs', json={'question': '试用期有多少天', 'top_k': 20})
        check('disabled_document_not_retrieved', all(c['document_id'] != first_doc for c in run['items']))
        old = request('GET', '/owner/retrieval-runs/' + first_run)
        check('history_rechecks_current_eligibility', all(c['document_id'] != first_doc for c in old['items']))
        request('PATCH', '/documents/' + first_doc + '/availability', json={'is_enabled': True})
        positive = [r['document_recall_at_5'] for r in report['retrievals'] if r['document_recall_at_5'] is not None]
        report['owner_tune_document_recall_at_5'] = sum(positive) / len(positive)
        report['positive_owner_case_count'] = len(positive)
        report['answer_accuracy'] = None
        report['status'] = 'PASSED'
        save()
        print('PASS real isolated retrieval acceptance; no LLM calls', flush=True)
    except Exception as error:
        report['status'] = 'FAILED'
        report['failure'] = str(error)
        save()
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
