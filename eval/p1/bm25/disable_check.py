"""Check both modes on an independent synthetic copy; no generation calls."""
import asyncio
import json
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-bm25/disable-20261008'
OUT.mkdir(parents=True,exist_ok=True)


async def main():
    credentials=json.loads((ROOT/'.auth/p1-preview/credentials.json').read_text(encoding='utf-8'))
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as client:
        async def call(method,path,**kwargs):
            response=await client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        auth=await call('POST','/auth/login',json=credentials)
        client.headers['Authorization']='Bearer '+auth['tokens']['access_token']
        space=await call('POST','/spaces',json={'name':'停用双模式复测-20261008','kind':'PERSONAL','visibility':'PRIVATE'})
        sid=space['id'];documents={}
        for path in sorted((ROOT/'eval/p1/bm25/materials').iterdir()):
            with path.open('rb') as stream:
                uploaded=await call('POST',f'/spaces/{sid}/documents',files={'file':(path.name,stream,'text/markdown' if path.suffix=='.md' else 'text/plain')})
            documents[path.name]=uploaded['document']['id']
        for _ in range(120):
            docs=await call('GET',f'/spaces/{sid}/documents')
            if any(x['status']=='FAILED' for x in docs['items']):raise RuntimeError('Synthetic processing failed')
            if len(docs['items'])==3 and all(x['status']=='READY' for x in docs['items']):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Synthetic processing timeout')
        did=documents['01-公开范围.txt'];results={}
        for phase,enabled in [('enabled',True),('disabled',False),('reenabled',True)]:
            await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':enabled})
            results[phase]={}
            for strategy in ['dense','bm25']:
                result=await call('POST',f'/owner/spaces/{sid}/retrieval-runs',json={'question':'SCOPE_CHANGED','strategy':strategy,'top_k':5})
                ids={x['document_id'] for x in result['items']}
                if enabled:assert did in ids,(phase,strategy,'enabled target missing')
                else:
                    assert did not in ids,(phase,strategy,'disabled target leaked')
                    if strategy=='bm25':assert result['items']==[]
                    else:assert result['items'],'other live dense candidates should remain'
                results[phase][strategy]=result
                print(phase,strategy,len(result['items']),sorted({x['document_name'] for x in result['items']}),flush=True)
        report={'status':'PASSED','date':'2026-10-08','query':'SCOPE_CHANGED','space_id':sid,
                'generation_calls':0,'user_documents_modified':False,'results':results,
                'conclusion':'Both modes exclude disabled 01. Dense may return other live candidates; BM25 has no exact keyword matches in this corpus.'}
        (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Disable/re-enable API checks PASSED',flush=True)


if __name__=='__main__':asyncio.run(main())
