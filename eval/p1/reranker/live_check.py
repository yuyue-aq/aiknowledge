import asyncio,hashlib,json,secrets,time,uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3]
FIX=ROOT/'eval/p1/reranker'
OUT=ROOT/'output/p1-reranker/live';OUT.mkdir(parents=True,exist_ok=True)
AUTH=ROOT/'.auth/p1-reranker';AUTH.mkdir(parents=True,exist_ok=True)

def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

async def main():
    manifest=json.loads((FIX/'manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((FIX/'cases.json').read_bytes()).hexdigest()==manifest['gold_sha256']
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=900) as c:
        async def call(method,path,**kwargs):
            r=await c.request(method,path,**kwargs);r.raise_for_status();return r.json() if r.content else None
        credentials={'email':f'c-rerank-{uuid.uuid4().hex[:10]}@example.test','password':'C-'+secrets.token_urlsafe(24)}
        registered=await call('POST','/auth/register',json={**credentials,'display_name':'重排阶段C验收'})
        (AUTH/'credentials.json').write_text(json.dumps(credentials),encoding='utf-8')
        c.headers['Authorization']='Bearer '+registered['tokens']['access_token']
        space=await call('POST','/spaces',json={'name':'P1 · 真实重排验收空间','kind':'TEAM','visibility':'PRIVATE'})
        sid=space['id'];docs={}
        for path in sorted((FIX/'materials').iterdir()):
            upload=await call('POST',f'/spaces/{sid}/documents',files={'file':(path.name,path.read_bytes(),'text/markdown')})
            docs[path.name]=upload['document']['id']
        for _ in range(180):
            documents=(await call('GET',f'/spaces/{sid}/documents'))['items']
            if any(item['status']=='FAILED' for item in documents):raise RuntimeError('Fixture processing failed')
            if len(documents)==4 and all(item['status']=='READY' for item in documents):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Fixture processing timed out')
        (AUTH/'state.json').write_text(json.dumps({'space_id':sid,'documents':docs}),encoding='utf-8')
        async def search(q,mode='hybrid_rerank'):
            return await call('POST',f'/owner/spaces/{sid}/retrieval-runs',json={'question':q,'strategy':mode,'top_k':3})
        rows=[]
        for case in json.loads((FIX/'cases.json').read_text(encoding='utf-8')):
            before=await search(case['question'],'hybrid');start=time.perf_counter();after=await search(case['question'])
            # Reconstruct the full baseline pool from its saved branch ranks.
            scores={}
            for items in before['config_snapshot']['branches'].values():
                for item in items:scores[item['chunk_id']]=scores.get(item['chunk_id'],0.)+1/(60+item['rank'])
            expected=sorted(scores,key=lambda cid:(-scores[cid],cid))[:50]
            actual=[item['chunk_id'] for item in after['config_snapshot']['branches']['fusion']]
            assert actual==expected,'Comparison pool changed'
            assert after['score_kind']=='cross_encoder' and after['config_snapshot']['reranker']['revision']=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
            assert all(not item['truncated'] for item in after['config_snapshot']['rerank_inputs'])
            saved=await call('GET','/owner/retrieval-runs/'+after['run_id'])
            assert saved['items']==after['items'] and saved['branches']==after['branches']
            def hit(result,k):
                return any(item['document_name']==case['expected_document'] and case['evidence_literal'] in item['content'] for item in result['items'][:k]) if case['answerable'] else None
            rows.append({**case,'before':before,'after':after,'seconds':time.perf_counter()-start,
                'before_hit1':hit(before,1),'after_hit1':hit(after,1),'before_hit3':hit(before,3),'after_hit3':hit(after,3)})
            save('paired-retrieval.json',rows);print(case['id'],'same pool; scored',flush=True)
        target=docs['01-青岚规则.md'];original=await search('青岚试用多少天？')
        await call('PATCH',f'/documents/{target}/availability',json={'is_enabled':False})
        disabled=await search('青岚试用多少天？')
        historical=await call('GET','/owner/retrieval-runs/'+original['run_id'])
        for run in [disabled,historical]:
            assert all(item['document_id']!=target for items in [run['items'],*run['branches'].values()] for item in items)
        await call('PATCH',f'/documents/{target}/availability',json={'is_enabled':True})
        summary={}
        for split in ['tune','holdout']:
            positive=[row for row in rows if row['split']==split and row['answerable']]
            summary[split]={'positive':len(positive),**{key:sum(row[key] for row in positive) for key in ['before_hit1','after_hit1','before_hit3','after_hit3']}}
        save('summary.json',{'status':'PASSED','space_id':sid,'cases':len(rows),'same_pool_checks':len(rows),
            'saved_contract_checks':len(rows),'scope_disabled_and_history':'PASSED','split_metrics':summary,
            'notes':'Literal evidence hit metrics, not answer accuracy. Unknown queries still produce candidates; refusal is separately tested.'})
        print('Real pinned reranker checks PASSED',flush=True)

if __name__=='__main__':asyncio.run(main())
