import asyncio,json,secrets,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'output/p1-reranker/runtime'

async def main():
    auth=json.loads((ROOT/'.auth/p1-rrf/credentials.json').read_text(encoding='utf-8'))
    sid=json.loads((OUT/'runtime-check.json').read_text(encoding='utf-8'))['space_id']
    checks=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=900) as c:
        async def call(method,path,**kwargs):
            r=await c.request(method,path,**kwargs);r.raise_for_status();return r.json() if r.content else None
        login=await call('POST','/auth/login',json=auth);owner=login['tokens']['access_token'];c.headers['Authorization']='Bearer '+owner
        account=await call('POST','/auth/register',json={'email':f'c-admin-{uuid.uuid4().hex[:8]}@example.test','password':'C-'+secrets.token_urlsafe(20),'display_name':'C重排管理员'})
        await call('POST',f'/spaces/{sid}/members',json={'email':account['user']['email'],'role':'ADMIN'})
        route=f'/owner/spaces/{sid}/retrieval-runs';payload={'question':'SCOPE_CHANGED','strategy':'hybrid_rerank','top_k':3}
        admin=await c.post(route,headers={'Authorization':'Bearer '+account['tokens']['access_token']},json=payload);admin.raise_for_status()
        assert admin.json()['score_kind']=='cross_encoder'
        await call('PATCH',f'/spaces/{sid}/members/{account["user"]["id"]}',json={'role':'MEMBER'})
        denied=await c.post(route,headers={'Authorization':'Bearer '+account['tokens']['access_token']},json=payload)
        assert denied.status_code==404
        checks.extend(['Team administrator real model allowed','Downgraded member denied before private diagnostics'])
        docs=(await call('GET',f'/spaces/{sid}/documents'))['items'];did=next(item['id'] for item in docs if item['original_filename']=='01-公开范围.txt')
        def items(run):return [*run['items'],*[item for values in run['branches'].values() for item in values]]
        try:
            for change in [{'expires_at':(datetime.now(UTC)-timedelta(seconds=5)).isoformat()},
                           {'expires_at':None,'effective_at':(datetime.now(UTC)+timedelta(days=1)).isoformat()}]:
                await call('PATCH',f'/documents/{did}/availability',json=change)
                result=await call('POST',route,json=payload)
                assert all(item['document_id']!=did for item in items(result))
            checks.extend(['Expired content never enters any real model branch','Future-effective content never enters any real model branch'])
        finally:await call('PATCH',f'/documents/{did}/availability',json={'effective_at':None,'expires_at':None})
        original=(ROOT/'eval/p1/bm25/materials/01-公开范围.txt').read_text(encoding='utf-8')
        for content,expected,absent in [(original.replace('SCOPE_CHANGED','SCOPE_RECHECKED'),'SCOPE_RECHECKED','SCOPE_CHANGED'),
                                        (original,'SCOPE_CHANGED','SCOPE_RECHECKED')]:
            accepted=await call('POST',f'/documents/{did}/versions',files={'file':('01-公开范围.txt',content.encode(),'text/plain')})
            for _ in range(120):
                current=(await call('GET',f'/spaces/{sid}/documents'))['items'];doc=next(item for item in current if item['id']==did)
                if doc['active_version_id']==accepted['version_id']:break
                await asyncio.sleep(2)
            else:raise RuntimeError('Model scope version update timed out')
            result=await call('POST',route,json={**payload,'question':absent})
            assert all(absent not in item['content'] for item in items(result))
            result=await call('POST',route,json={**payload,'question':expected})
            assert any(expected in item['content'] for item in result['items'])
        checks.append('Inactive version removed; current version real model used and original fixture restored')
        (OUT/'scope-check.json').write_text(json.dumps({'status':'PASSED','space_id':sid,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Real model scope checks PASSED',len(checks),flush=True)

if __name__=='__main__':asyncio.run(main())
