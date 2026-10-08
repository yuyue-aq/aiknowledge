"""Real P1 API checks; creates only synthetic data, never calls generation."""
import asyncio
from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
import secrets
import time
import uuid
import httpx

ROOT=Path(__file__).resolve().parents[3]
FIXTURES=ROOT/'eval/p1/bm25'
OUT=ROOT/'output/p1-bm25'
OUT.mkdir(parents=True,exist_ok=True)
AUTH=ROOT/'.auth/p1-preview'
AUTH.mkdir(parents=True,exist_ok=True)

def save(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as client:
        async def call(method,path,**kwargs):
            response=await client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        accounts=[]
        for label in ['owner','admin','outsider']:
            email=f'p1-{label}-{uuid.uuid4().hex[:12]}@example.test'
            password='P1-'+secrets.token_urlsafe(20)
            registered=await call('POST','/auth/register',json={'email':email,'password':password,'display_name':f'BM25测试{label}'})
            accounts.append({'email':email,'password':password,'id':registered['user']['id'],'token':registered['tokens']['access_token']})
        owner,admin,outsider=accounts
        (AUTH/'credentials.json').write_text(json.dumps({'email':owner['email'],'password':owner['password']},ensure_ascii=False),encoding='utf-8')
        client.headers['Authorization']='Bearer '+owner['token']
        space=await call('POST','/spaces',json={'name':'P1 · BM25 人工验收空间','kind':'TEAM','visibility':'PRIVATE'})
        sid=space['id'];docs={}
        for path in sorted((FIXTURES/'materials').iterdir()):
            with path.open('rb') as stream:
                result=await call('POST',f'/spaces/{sid}/documents',files={'file':(path.name,stream,'text/markdown' if path.suffix=='.md' else 'text/plain')})
            docs[path.name]=result['document']['id']
        for attempt in range(120):
            current=await call('GET',f'/spaces/{sid}/documents')
            if any(d['status']=='FAILED' for d in current['items']):raise RuntimeError('Synthetic processing failed')
            if all(d['status']=='READY' for d in current['items']):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Synthetic documents did not become ready')
        route=f'/owner/spaces/{sid}/retrieval-runs'
        cases=json.loads((FIXTURES/'questions.json').read_text(encoding='utf-8'))
        responses=[]
        for case in cases:
            row={**case,'results':{}}
            for mode in ['bm25','dense']:
                started=time.perf_counter()
                result=await call('POST',route,json={'question':case['question'],'top_k':3,'strategy':mode})
                if mode=='bm25':assert result['timings_ms']['embedding']==0 and result['score_kind']=='bm25'
                expected=case['expected_document']
                row['results'][mode]={'response':result,'client_seconds':time.perf_counter()-started,
                    'hit_at_1':bool(result['items']) and result['items'][0]['document_name']==expected if expected else None,
                    'hit_at_3':any(x['document_name']==expected for x in result['items']) if expected else None,
                    'evidence_hit':any(x['document_name']==expected and case['evidence_literal'] in x['content'] for x in result['items']) if expected else None}
            responses.append(row);save('retrieval-comparison.json',responses)
            print(case['id'],'measured',flush=True)
        original=await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'})
        assert original['items'] and original['items'][0]['document_id']==docs['01-公开范围.txt']
        did=docs['01-公开范围.txt']
        await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
        disabled=await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'})
        saved=await call('GET',f'/owner/retrieval-runs/{original["run_id"]}')
        assert disabled['items']==[] and saved['items']==[] and saved['unavailable_chunk_ids']
        await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True,'expires_at':(datetime.now(UTC)-timedelta(seconds=5)).isoformat()})
        assert (await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'}))['items']==[]
        await call('PATCH',f'/documents/{did}/availability',json={'expires_at':None,'effective_at':(datetime.now(UTC)+timedelta(days=1)).isoformat()})
        assert (await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'}))['items']==[]
        await call('PATCH',f'/documents/{did}/availability',json={'effective_at':None})
        await call('POST',f'/spaces/{sid}/members',json={'email':admin['email'],'role':'ADMIN'})
        client.headers['Authorization']='Bearer '+admin['token']
        assert (await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'}))['items']
        client.headers['Authorization']='Bearer '+owner['token']
        await call('PATCH',f'/spaces/{sid}/members/{admin["id"]}',json={'role':'MEMBER'})
        for token in [admin['token'],outsider['token']]:
            response=await client.post(route,headers={'Authorization':'Bearer '+token},json={'question':'SCOPE_CHANGED','strategy':'bm25'})
            assert response.status_code==404
        # A caller owning two spaces must still search only the selected space;
        # foreign chunks must not influence even scope-local BM25 statistics.
        before=await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'})
        foreign=await call('POST','/spaces',json={'name':'BM25跨空间隔离B','kind':'PERSONAL','visibility':'PRIVATE'})
        uploaded=await call('POST',f'/spaces/{foreign["id"]}/documents',files={'file':('隔离B.txt',b'CROSS_SPACE_ONLY_51963','text/plain')})
        for _ in range(120):
            current=await call('GET',f'/spaces/{foreign["id"]}/documents')
            if all(x['status']=='READY' for x in current['items']):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Foreign synthetic document not ready')
        assert (await call('POST',route,json={'question':'CROSS_SPACE_ONLY_51963','strategy':'bm25'}))['items']==[]
        after=await call('POST',route,json={'question':'SCOPE_CHANGED','strategy':'bm25'})
        assert [x['score'] for x in before['items']]==[x['score'] for x in after['items']]
        # Verify activity-version filtering against real index replacements.
        original_text=(FIXTURES/'materials/01-公开范围.txt').read_text(encoding='utf-8')
        for content,expected,absent in [(original_text.replace('SCOPE_CHANGED','SCOPE_RECHECKED'),'SCOPE_RECHECKED','SCOPE_CHANGED'),
                                       (original_text,'SCOPE_CHANGED','SCOPE_RECHECKED')]:
            replacement=await call('POST',f'/documents/{did}/versions',files={'file':('01-公开范围.txt',content.encode(),'text/plain')})
            for _ in range(120):
                current=await call('GET',f'/spaces/{sid}/documents')
                document=next(x for x in current['items'] if x['id']==did)
                if document['active_version_id']==replacement['version_id']:break
                await asyncio.sleep(2)
            else:raise RuntimeError('Replacement did not activate')
            assert (await call('POST',route,json={'question':absent,'strategy':'bm25'}))['items']==[]
            assert (await call('POST',route,json={'question':expected,'strategy':'bm25'}))['items']
        historic=await call('GET',f'/owner/retrieval-runs/{original["run_id"]}')
        assert historic['items']==[] and historic['unavailable_chunk_ids']
        client.headers.pop('Authorization')
        assert (await client.post(route,json={'question':'SCOPE_CHANGED','strategy':'bm25'})).status_code==401
        save('live-check.json',{'status':'PASSED','space_id':sid,'documents':docs,'checks':['BM25 no query embedding','saved strategy and score semantics','disabled hidden','historical source unavailable','expired hidden','future-effective hidden','team admin allowed','downgraded member denied','outsider denied','cross-space corpus excluded','foreign corpus does not alter local scores','old version excluded after replacement','historical version hidden','unauthenticated denied'],
            'generation_calls':0,'scope':'Only P1 isolated database and synthetic materials; no original documents modified'})
        print('Real API checks PASSED',flush=True)

if __name__=='__main__':asyncio.run(main())
