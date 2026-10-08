"""Read final browser-dispatched Worker results and verify persisted reviews."""
import asyncio,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-reranker/acceptance-20261008';AUTH=ROOT/'.auth/p1-c-acceptance'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))

async def main():
    ui=read(OUT/'ui.json');scope=read(OUT/'scope.json');grading=read(OUT/'grading.json')
    assert ui['status']==scope['status']==grading['status']=='PASSED'
    details=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=30) as c:
        login=await c.post('/auth/login',json=read(AUTH/'credentials.json'));login.raise_for_status()
        c.headers['Authorization']='Bearer '+login.json()['tokens']['access_token']
        for run in ui['runs']:
            r=await c.get('/eval-runs/'+run['id']);r.raise_for_status();detail=r.json()
            strategy=detail['run']['retrieval_config_snapshot']['retrieval_strategy']
            assert detail['run']['status']=='COMPLETED' and len(detail['results'])==3
            cases={x['id']:x for x in detail['run']['retrieval_config_snapshot']['eval_cases']}
            for result in detail['results']:
                assert result['execution_snapshot']['retrieval_strategy']==strategy
                q=cases[result['eval_case_id']]['question'];answer=result['answer']
                if '公网地址' in q:assert result['answer_status']=='INSUFFICIENT_EVIDENCE'
                else:
                    assert result['answer_status']=='ANSWERED'
                    assert ('17' if '青岚' in q else '90') in answer
                if strategy=='hybrid_rerank':
                    assert result['reviewer_score']==1
                    cfg=result['execution_snapshot']['retrieval_config']
                    assert cfg['reranker']['revision']=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
                    assert all(x['truncated'] is False for x in cfg['rerank_inputs'])
            details.append(detail)
        assert details[0]['run']['retrieval_config_snapshot']['knowledge_manifest']==details[1]['run']['retrieval_config_snapshot']['knowledge_manifest']
        assert details[0]['run']['retrieval_config_snapshot']['eval_set_version_id']==details[1]['run']['retrieval_config_snapshot']['eval_set_version_id']
    (OUT/'worker-final.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'status':'PASSED','space_id':scope['space_id'],'ui_groups':len(ui['checks']),'scope_groups':len(scope['checks']),
        'assistant_ui_reviewed_cases':len(grading['grades']),'worker_runs_completed':len(details),'same_knowledge_manifest':True,
        'model_revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','known_500_failures_preserved':6,
        'notes':'Only new synthetic acceptance space; controlled 503 tests UI error handling. No fake successful model responses. Three assistant UI reviews are not independent human evaluation of 500 cases.'}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
