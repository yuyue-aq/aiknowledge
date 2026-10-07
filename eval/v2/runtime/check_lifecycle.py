"""Real synthetic version/expiry/delete and async-failure acceptance, no LLM key."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'eval/v2/runtime/lifecycle_report.json'
BASE = 'http://127.0.0.1:18000/api/v1'


def main():
    report = {'mode': 'real_isolated_version_and_async_no_llm', 'checks': [], 'llm_calls': 0}
    client = httpx.Client(base_url=BASE, timeout=700)
    def check(label, condition):
        assert condition, label
        report['checks'].append(label)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS ' + label, flush=True)
    def api(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        assert r.status_code < 400, f'{method} {path}: HTTP {r.status_code}'
        return r.json() if r.content else None
    def until(function, predicate, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = function()
            if predicate(value):
                return value
            time.sleep(2)
        raise TimeoutError('Synthetic runtime condition did not complete')
    try:
        auth = api('POST', '/auth/register', json={'email': 'lifecycle-' + uuid.uuid4().hex + '@example.test',
                  'password': secrets.token_urlsafe(24), 'display_name': 'V2 生命周期验收'})
        client.headers['Authorization'] = 'Bearer ' + auth['tokens']['access_token']
        sid = api('POST', '/spaces', json={'name': 'V2 lifecycle synthetic', 'visibility': 'PRIVATE'})['id']
        report['space_id'] = sid
        submitted = api('POST', f'/spaces/{sid}/documents', files={'file': ('old.txt', '试用期为14天。'.encode(), 'text/plain')})
        did = submitted['document']['id']
        v1 = submitted['version_id']
        report['document_id'] = did
        until(lambda: api('GET', '/documents/' + did), lambda d: d['status'] == 'READY')
        detail_path = f'/owner/spaces/{sid}/documents/{did}'
        check('initial_real_version_ready', api('GET', detail_path)['document']['active_version_id'] == v1)
        rejected = client.post(f'/documents/{did}/versions', files={'file': ('invalid.pdf', b'not a pdf file', 'application/pdf')})
        check('invalid_file_signature_rejected', rejected.status_code == 422)
        bad = api('POST', f'/documents/{did}/versions', files={'file': ('bad.pdf', b'%PDF-1.7\nmalformed body\n%%EOF', 'application/pdf')})
        v2 = bad['version_id']
        check('new_submission_keeps_old_activity', bad['document']['active_version_id'] == v1 and bad['document']['status'] == 'READY')
        def failed(detail):
            return any(v['id'] == v2 and v['status'] == 'FAILED' for v in detail['versions'])
        detail = until(lambda: api('GET', detail_path), failed)
        check('parse_failure_retains_old_source', detail['document']['active_version_id'] == v1 and detail['document']['original_filename'] == 'old.txt')
        check('parse_failure_retains_old_chunks', all(c['document_version_id'] == v1 for c in detail['chunks']))
        retry = api('POST', f'/documents/{did}/versions/{v2}/retry')
        check('failed_version_retry_queued', retry['version_id'] == v2 and retry['processing_enqueued'])
        until(lambda: api('GET', detail_path), failed)
        replacement = api('POST', f'/documents/{did}/versions', files={'file': ('new.txt', '试用期更新为21天。'.encode(), 'text/plain')})
        v3 = replacement['version_id']
        detail = until(lambda: api('GET', detail_path), lambda d: d['document']['active_version_id'] == v3)
        check('successful_update_switches_source', detail['document']['original_filename'] == 'new.txt')
        check('only_current_version_chunks_visible', bool(detail['chunks']) and all(c['document_version_id'] == v3 for c in detail['chunks']))
        run = api('POST', f'/owner/spaces/{sid}/retrieval-runs', json={'question': '试用期几天', 'top_k': 5})
        check('retrieval_reads_updated_fact', bool(run['items']) and all('21天' in c['content'] for c in run['items']))
        # One actual async execution with a deliberately absent provider key.
        # FAILED must remain FAILED, not a correct refusal/quality success.
        case = api('POST', f'/spaces/{sid}/eval-cases', json={'question': '试用期几天', 'expected_answer': '21天',
                   'expected_document_ids': [did], 'scope': 'OWNER', 'answerable': True, 'expected_behavior': 'ANSWERED'})
        version = api('POST', f'/spaces/{sid}/eval-versions', json={'label': 'failure-path-only', 'case_ids': [case['id']]})
        queued = api('POST', '/eval-versions/' + version['id'] + '/runs/async')
        check('async_returns_pending', queued['status'] == 'PENDING')
        result = until(lambda: api('GET', '/eval-runs/' + queued['id']), lambda d: d['run']['status'] in ('COMPLETED', 'FAILED', 'STOPPED'))
        check('worker_persists_case_checkpoint', result['run']['progress_completed'] == 1 and len(result['results']) == 1)
        record = result['results'][0]
        check('missing_model_remains_generation_failure', record['answer_status'] == 'FAILED')
        check('generation_failure_retains_retrieval_metrics', record['retrieval_metrics']['document_recall_at_k'] == 1.0)
        evidence = api('GET', f'/owner/eval-runs/{queued["id"]}/results/{record["id"]}/evidence')
        check('saved_execution_evidence_available', evidence['snapshot_available'] and bool(evidence['items']))
        report['async_run_id'] = queued['id']
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        api('PATCH', '/documents/' + did + '/availability', json={'expires_at': past})
        expired = api('POST', f'/owner/spaces/{sid}/retrieval-runs', json={'question': '试用期几天', 'top_k': 5})
        check('expired_source_not_retrieved', expired['items'] == [])
        stale = api('GET', f'/owner/eval-runs/{queued["id"]}/results/{record["id"]}/evidence')
        check('saved_evidence_rechecks_expiry', stale['items'] == [] and bool(stale['unavailable_chunk_ids']))
        api('PATCH', '/documents/' + did + '/availability', json={'expires_at': None})
        api('DELETE', '/documents/' + did)
        deleted = api('POST', f'/owner/spaces/{sid}/retrieval-runs', json={'question': '试用期几天', 'top_k': 5})
        check('deleted_source_immediately_excluded', deleted['items'] == [])
        report['version_ids'] = [v1, v2, v3]
        report['status'] = 'PASSED'
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        report['status'] = 'FAILED'
        report['failure'] = str(error)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
