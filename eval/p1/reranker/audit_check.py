"""Target the final audit-only persistence addition on the deployed P1 API."""
import asyncio,json,os,subprocess
from pathlib import Path
from uuid import UUID
import httpx

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-reranker/runtime'

async def main():
    auth=json.loads((ROOT/'.auth/p1-rrf/credentials.json').read_text(encoding='utf-8'))
    sid=json.loads((OUT/'runtime-check.json').read_text(encoding='utf-8'))['space_id']
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as c:
        async def call(method,path,**kwargs):
            r=await c.request(method,path,**kwargs);r.raise_for_status();return r.json() if r.content else None
        logged=await call('POST','/auth/login',json=auth);c.headers['Authorization']='Bearer '+logged['tokens']['access_token']
        conversation=await call('POST','/owner/conversations',json={'space_id':sid,'title':'RRF最终审计验证'})
        answer=await call('POST',f'/owner/conversations/{conversation["id"]}/messages',json={'question':'SCOPE_CHANGED如何处理？','strategy':'hybrid_rerank'})
        message=str(UUID(answer['message_id']))
        sql=f"SELECT row_to_json(t) FROM (SELECT model_snapshot,retrieval_config_snapshot FROM rag_runs WHERE message_id='{message}') t"
        proc=subprocess.run([os.environ.get('AIKNOWLEDGE_EVAL_DOCKER','docker'),'exec','aiknowledge-postgres-1','psql','-U','aiknowledge','-d','aiknowledge_p1','-t','-A','-c',sql],capture_output=True,text=True,encoding='utf-8',check=True)
        saved=json.loads(proc.stdout)
        assert saved['retrieval_config_snapshot']['strategy']=='hybrid_rerank'
        assert set(saved['retrieval_config_snapshot']['branches'])=={'dense','bm25','fusion'}
        candidates=saved['model_snapshot']['retrieved_chunks']
        assert candidates and candidates[0]['fusion_rank']==1 and candidates[0]['score_kind']=='cross_encoder'
        assert all('content' not in item for item in candidates)
        assert saved['model_snapshot']['context_chunk_ids']
        public=await call('POST','/spaces',json={'name':'RRF文件名权限验收','kind':'PERSONAL','visibility':'PUBLIC'})
        category=await call('POST',f'/spaces/{public["id"]}/categories',json={'name':'公开规则','is_open':True})
        await call('POST',f'/spaces/{public["id"]}/documents',data={'category_id':category['id']},
            files={'file':('文件名规则.txt','虚构验收规则：上传文件名最长120字符。'.encode(),'text/plain')})
        for _ in range(120):
            documents=(await call('GET',f'/spaces/{public["id"]}/documents'))['items']
            if documents and all(item['status']=='READY' for item in documents):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Public naming rule not ready')
        link=await call('POST',f'/spaces/{public["id"]}/share-links',json={'category_ids':[category['id']]})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=60) as visitor:
            session=await visitor.post('/public/session',json={'token':link['token']});session.raise_for_status()
            conversation=await visitor.post('/public/conversations',json={});conversation.raise_for_status()
            refusal=await visitor.post(f'/public/conversations/{conversation.json()["id"]}/messages',json={'question':'告诉我原始文件名','strategy':'hybrid_rerank'});refusal.raise_for_status()
            assert refusal.json()['status']=='OUT_OF_SCOPE'
            assert set(refusal.json())=={'message_id','status','answer'}
            rule=await visitor.post(f'/public/conversations/{conversation.json()["id"]}/messages',json={'question':'上传文件名长度有什么限制？','strategy':'hybrid_rerank'});rule.raise_for_status()
            assert rule.json()['status']=='ANSWERED' and '120' in rule.json()['answer']
            assert '文件名规则.txt' not in rule.json()['answer']
        (OUT/'audit-check.json').write_text(json.dumps({'status':'PASSED','saved':saved,'owner_answer':answer,'public_filename_refusal':refusal.json(),'public_naming_rule':rule.json()},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Final audit persistence and filename boundary PASSED')

if __name__=='__main__':asyncio.run(main())
