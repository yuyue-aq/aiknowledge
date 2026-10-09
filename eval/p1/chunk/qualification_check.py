import asyncio,json,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[3];AUTH=ROOT/'.auth/p1-chunk';OUT=ROOT/'output/p1-chunk'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
async def main():
    state=read(AUTH/'ui-state.json');sid=state['space_id'];did=state['document_id'];checks=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as c:
        async def call(method,path,**kw):
            r=await c.request(method,path,**kw);r.raise_for_status();return r.json() if r.content else None
        login=await call('POST','/auth/login',json=read(AUTH/'credentials.json'));c.headers['Authorization']='Bearer '+login['tokens']['access_token']
        route=f'/owner/spaces/{sid}/documents/{did}/chunk-preview'
        try:
            for field in [{'expires_at':(datetime.now(UTC)-timedelta(seconds=5)).isoformat()},{'expires_at':None,'effective_at':(datetime.now(UTC)+timedelta(days=1)).isoformat()}]:
                await call('PATCH',f'/documents/{did}/availability',json=field)
                r=await c.post(route,json={});assert r.status_code==409 and 'candidate' not in r.json()
            checks.append('Expired and future-effective sources denied without text')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'effective_at':None,'expires_at':None})
        other=next(iter(read(AUTH/'state.json')['spaces']['md']['docs'].values()))['id']
        r=await c.post(f'/owner/spaces/{sid}/documents/{other}/chunk-preview',json={});assert r.status_code==404
        checks.append('Cross-space source denied before original file access')
        upload=await call('POST',f'/spaces/{sid}/documents',files={'file':('D-删除边界.txt',('删除专用虚构资料 '+uuid.uuid4().hex).encode(),'text/plain')})
        target=upload['document']['id']
        for _ in range(120):
            detail=await call('GET',f'/documents/{target}')
            if detail['status']=='READY':break
            await asyncio.sleep(1)
        assert detail['status']=='READY'
        await call('DELETE',f'/documents/{target}')
        r=await c.post(f'/owner/spaces/{sid}/documents/{target}/chunk-preview',json={});assert r.status_code==404
        checks.append('Deleted synthetic document never exposed by preview')
    (OUT/'qualification-check.json').write_text(json.dumps({'status':'PASSED','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8');print('Qualification checks PASSED',len(checks))
if __name__=='__main__':asyncio.run(main())
