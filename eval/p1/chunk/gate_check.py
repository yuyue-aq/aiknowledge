import asyncio,json,os,secrets,subprocess,sys,uuid
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[3];AUTH=ROOT/'.auth/p1-chunk';OUT=ROOT/'output/p1-chunk/gates'
DOCKER=os.environ.get('AIKNOWLEDGE_EVAL_DOCKER','D:/develop/Docker/resources/bin/docker.exe')
BASE='http://127.0.0.1:10087/api/v1'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def docker(*args):subprocess.run([DOCKER,*args],check=True,capture_output=True)

async def main():
    async with httpx.AsyncClient(base_url=BASE,timeout=660) as c:
        async def call(method,path,**kw):
            r=await c.request(method,path,**kw);r.raise_for_status();return r.json() if r.content else None
        login=await call('POST','/auth/login',json=read(AUTH/'credentials.json'));c.headers['Authorization']='Bearer '+login['tokens']['access_token']
        async def ready(sid,did,vid=None,failed=None):
            for _ in range(240):
                detail=await call('GET',f'/owner/spaces/{sid}/documents/{did}')
                if failed and next(x for x in detail['versions'] if x['id']==failed)['status']=='FAILED':return detail
                if vid and detail['document']['active_version_id']==vid:return detail
                if not vid and not failed and detail['document']['status']=='READY':return detail
                await asyncio.sleep(1)
            raise RuntimeError('Gate worker timeout')
        if sys.argv[1]=='seed':
            space=await call('POST','/spaces',json={'name':'D阶段 · 页面与边界验收','kind':'TEAM','visibility':'PRIVATE'})
            body=(ROOT/'eval/p1/chunk/materials/01-青桥.txt').read_text(encoding='utf-8')
            for i in range(11,36):body+=f'\n{i:02d} 布局测试{i}\n仅用于长列表与分页验证，不改变青桥的服务规则。\n'
            accepted=await call('POST',f'/spaces/{space["id"]}/documents',files={'file':('D-长段落验收.txt',body.encode(),'text/plain')})
            detail=await ready(space['id'],accepted['document']['id'])
            save(AUTH/'ui-state.json',{'space_id':space['id'],'space_name':space['name'],'document_id':detail['document']['id'],'filename':'D-长段落验收.txt'})
            print('UI gate fixture READY',flush=True);return
        state=read(AUTH/'ui-state.json');sid=state['space_id'];did=state['document_id'];route=f'/owner/spaces/{sid}/documents/{did}'
        checks=[]
        def passed(name):checks.append(name);save(OUT/'progress.json',{'status':'IN_PROGRESS','checks':checks});print('PASS',name,flush=True)
        cfg={'strategy':'structure','max_tokens':256,'overlap_characters':80}
        async def preview():return await call('POST',route+'/chunk-preview',json={**cfg,'limit':50})
        # Freeze pending worker to deterministically inspect old-version retention.
        p=await preview();before=await call('GET',route)
        docker('pause','aiknowledge-p1-p1-worker-1')
        try:
            accepted=await call('POST',route+'/rechunk',json={**cfg,'expected_version_id':p['document_version_id'],'fingerprint':p['fingerprint']})
            pending=await call('GET',route)
            assert pending['document']['active_version_id']==before['document']['active_version_id']
            assert [x['chunk_id'] for x in pending['chunks']]==[x['chunk_id'] for x in before['chunks']]
            duplicate=await c.post(route+'/rechunk',json={**cfg,'expected_version_id':p['document_version_id'],'fingerprint':p['fingerprint']})
            assert duplicate.status_code==409
            passed('Pending real rebuild retains old active index and duplicate submission is rejected')
        finally:docker('unpause','aiknowledge-p1-p1-worker-1')
        current=await ready(sid,did,accepted['version_id'])
        assert len(current['chunks'])==p['candidate_total']
        passed('Worker activates actual preview strategy/configuration and new chunk count')
        stale=await c.post(route+'/rechunk',json={**cfg,'expected_version_id':p['document_version_id'],'fingerprint':p['fingerprint']});assert stale.status_code==409
        passed('Old preview cannot overwrite a newer active version')
        cfg={**cfg,'max_tokens':384};p=await preview()
        docker('pause','aiknowledge-p1-p1-worker-1')
        try:
            broken=await call('POST',route+'/rechunk',json={**cfg,'expected_version_id':p['document_version_id'],'fingerprint':p['fingerprint']})
            vid=str(uuid.UUID(broken['version_id']))
            sql=f"UPDATE document_versions SET chunk_config=jsonb_set(chunk_config,'{{configuration_fingerprint}}','\"test-corruption\"'::jsonb) WHERE id='{vid}' AND document_id='{uuid.UUID(did)}';"
            subprocess.run([DOCKER,'exec','-i','aiknowledge-postgres-1','psql','-U','aiknowledge','-d','aiknowledge_p1','-v','ON_ERROR_STOP=1'],input=sql,text=True,capture_output=True,check=True)
        finally:docker('unpause','aiknowledge-p1-p1-worker-1')
        failed=await ready(sid,did,failed=vid)
        assert failed['document']['active_version_id']==current['document']['active_version_id']
        passed('Corrupted frozen config fails real processing; old active version is retained')
        # Repair only this synthetic failed version, then verify admin-only retry.
        snapshot=json.dumps(p['candidate_config'],ensure_ascii=True).replace("'","''")
        sql=f"UPDATE document_versions SET chunk_config='{snapshot}'::jsonb WHERE id='{vid}' AND document_id='{uuid.UUID(did)}';"
        subprocess.run([DOCKER,'exec','-i','aiknowledge-postgres-1','psql','-U','aiknowledge','-d','aiknowledge_p1','-v','ON_ERROR_STOP=1'],input=sql,text=True,capture_output=True,check=True)
        credentials={'email':f'd-admin-{uuid.uuid4().hex[:8]}@example.test','password':'D-'+secrets.token_urlsafe(20)}
        admin=await call('POST','/auth/register',json={**credentials,'display_name':'D边界管理员'})
        await call('POST',f'/spaces/{sid}/members',json={'email':credentials['email'],'role':'ADMIN'})
        admin_headers={'Authorization':'Bearer '+admin['tokens']['access_token']}
        r=await c.post(route+'/chunk-preview',headers=admin_headers,json=cfg);r.raise_for_status()
        await call('PATCH',f'/spaces/{sid}/members/{admin["user"]["id"]}',json={'role':'EDITOR'})
        assert (await c.post(route+'/chunk-preview',headers=admin_headers,json=cfg)).status_code==404
        assert (await c.post(f'/documents/{did}/versions/{vid}/retry',headers=admin_headers)).status_code==403
        passed('Team admin may preview; downgraded editor cannot preview or retry admin rebuild')
        retried=await call('POST',f'/documents/{did}/versions/{vid}/retry');assert retried['processing_enqueued']
        recovered=await ready(sid,did,vid)
        assert next(x for x in recovered['versions'] if x['id']==vid)['chunk_config']==p['candidate_config']
        passed('Owner retry recovers real failed version with frozen configuration')
        try:
            await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
            r=await c.post(route+'/chunk-preview',json=cfg);assert r.status_code==409 and 'current' not in r.json()
            passed('Disabled source cannot be read through preview')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True})
        async with httpx.AsyncClient(base_url=BASE) as visitor:
            assert (await visitor.post(route+'/chunk-preview',json=cfg)).status_code==401
            assert (await visitor.post(route+'/rechunk',json={**cfg,'expected_version_id':vid,'fingerprint':'a'*64})).status_code==401
        passed('Anonymous visitor cannot preview private text or trigger rebuild')
        save(OUT/'summary.json',{'status':'PASSED','checks':checks,'space_id':sid,'document_id':did,'isolated_synthetic_only':True})

if __name__=='__main__':asyncio.run(main())
