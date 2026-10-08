"""Fresh phase C acceptance fixtures and live lifecycle/authorization gates."""
import asyncio,json,secrets,sys,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3]
AUTH=ROOT/'.auth/p1-c-acceptance';OUT=ROOT/'output/p1-reranker/acceptance-20261008'
BASE='http://127.0.0.1:10087/api/v1'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def items(r):return [*r['items'],*[x for lane in r['branches'].values() for x in lane]]

async def main():
    checks=[]
    def passed(name):
        checks.append(name);print('PASS',name,flush=True)
        save(OUT/'scope-progress.json',{'status':'IN_PROGRESS','checks':checks})
    async with httpx.AsyncClient(base_url=BASE,timeout=660) as c:
        async def call(method,path,**kw):
            r=await c.request(method,path,**kw);r.raise_for_status();return r.json() if r.content else None
        async def ready(sid,did,version=None):
            for _ in range(120):
                d=next(x for x in (await call('GET',f'/spaces/{sid}/documents'))['items'] if x['id']==did)
                if d['status']=='FAILED':raise RuntimeError('Synthetic upload failed')
                if d['status']=='READY' and (not version or d['active_version_id']==version):return d
                await asyncio.sleep(1)
            raise RuntimeError('Synthetic upload timeout')
        if sys.argv[1]=='seed':
            credential={'email':f'c-accept-{uuid.uuid4().hex[:10]}@example.test','password':'C-'+secrets.token_urlsafe(24)}
            registered=await call('POST','/auth/register',json={**credential,'display_name':'C阶段代验收'})
            save(AUTH/'credentials.json',credential);c.headers['Authorization']='Bearer '+registered['tokens']['access_token']
            name='C阶段 · 代验收 '+uuid.uuid4().hex[:6]
            space=await call('POST','/spaces',json={'name':name,'kind':'TEAM','visibility':'PUBLIC'})
            sid=space['id'];categories={}
            for label,opened in [('公开验证',True),('内部验证',False)]:
                categories[label]=await call('POST',f'/spaces/{sid}/categories',json={'name':label,'is_open':opened})
            docs={}
            for i,p in enumerate(sorted((ROOT/'eval/p1/reranker/materials').glob('*.md'))):
                upload=await call('POST',f'/spaces/{sid}/documents',data={'category_id':categories['公开验证' if i<2 else '内部验证']['id']},files={'file':(p.name,p.read_bytes(),'text/markdown')})
                docs[p.name]=upload['document']['id'];await ready(sid,docs[p.name])
            cases=[]
            for q,answer,filename,answerable in [('青岚测试版可以试用多少天？','17天。','01-青岚规则.md',True),('云栈停用后资料保存多久？','90天。','03-云栈规则.md',True),('青岚的真实公网地址是什么？','资料未提供，不应编造。',None,False)]:
                case=await call('POST',f'/spaces/{sid}/eval-cases',json={'question':q,'expected_answer':answer,'scope':'OWNER','category_ids':[],'expected_document_ids':[docs[filename]] if filename else [],'answerable':answerable,'expected_behavior':'ANSWERED' if answerable else 'INSUFFICIENT_EVIDENCE'})
                cases.append(case['id'])
            version=await call('POST',f'/spaces/{sid}/eval-versions',json={'label':'C代验收冻结三题','case_ids':cases})
            save(AUTH/'state.json',{'space_id':sid,'space_name':name,'documents':docs,'categories':categories,'version_id':version['id']})
            passed('Fresh independent team space and four approved synthetic documents READY')
            save(OUT/'seed.json',{'status':'PASSED','space_id':sid,'space_name':name,'documents':docs,'version_id':version['id']})
            return
        login=await call('POST','/auth/login',json=read(AUTH/'credentials.json'))
        c.headers['Authorization']='Bearer '+login['tokens']['access_token'];state=read(AUTH/'state.json')
        sid=state['space_id'];docs=state['documents'];did=docs['01-青岚规则.md']
        route=f'/owner/spaces/{sid}/retrieval-runs'
        if sys.argv[1]=='overflow':
            r=await c.post(route,json={'question':'请说明此问题。'*150,'strategy':'hybrid_rerank','top_k':5})
            save(OUT/'input-limit.json',{'status_code':r.status_code,'body':r.json()})
            print(r.status_code,json.dumps(r.json(),ensure_ascii=False),flush=True)
            return
        async def retrieve(q):return await call('POST',route,json={'question':q,'strategy':'hybrid_rerank','top_k':5})
        original=await retrieve('青岚访客能下载原文件吗？')
        assert original['config_snapshot']['reranker']['revision']=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
        saved=await call('GET','/owner/retrieval-runs/'+original['run_id']);assert saved['items']==original['items']
        passed('Pinned actual model and saved score/rank contract')
        oversized=await c.post(route,json={'question':'请说明此问题。'*150,'strategy':'hybrid_rerank','top_k':5})
        save(OUT/'input-limit.json',{'status_code':oversized.status_code,'body':oversized.json()})
        assert oversized.status_code==422 and oversized.json()['code'] in ('QUERY_TOKEN_LIMIT','RERANK_INPUT_LIMIT')
        passed('Long query explicitly rejected by upstream/model token validation, no silent truncation')
        try:
            await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
            assert all(x['document_id']!=did for x in items(await retrieve('青岚试用时间是多少？')))
            historical=await call('GET','/owner/retrieval-runs/'+original['run_id'])
            assert all(x['document_id']!=did for x in items(historical))
            con=await call('POST','/owner/conversations',json={'space_id':sid})
            response=await call('POST',f'/owner/conversations/{con["id"]}/messages',json={'question':'青岚测试版可以试用多少天？','strategy':'hybrid_rerank'})
            assert response['status']=='INSUFFICIENT_EVIDENCE' and '17' not in response['answer']
            passed('Disabled source excluded in new retrieval, historical read and new answer')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True})
        try:
            for change in [{'expires_at':(datetime.now(UTC)-timedelta(seconds=5)).isoformat()},{'expires_at':None,'effective_at':(datetime.now(UTC)+timedelta(days=1)).isoformat()}]:
                await call('PATCH',f'/documents/{did}/availability',json=change)
                assert all(x['document_id']!=did for x in items(await retrieve('青岚试用时间')))
            passed('Expired and future-effective documents excluded from every branch')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'effective_at':None,'expires_at':None})
        # Real pending model request; revocation occurs while it is still in flight.
        task=asyncio.create_task(c.post(route,json={'question':'青岚访客能下载原文件吗？','strategy':'hybrid_rerank','top_k':5}))
        await asyncio.sleep(.5);assert not task.done(),'In-flight check missed request window'
        try:
            await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
            revoked=await task
            assert revoked.status_code==409 and revoked.json()['code']=='RETRIEVAL_SCOPE_CHANGED',revoked.status_code
            passed('In-flight real request rejects old scope with 409 and no result')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True})
        original_text=(ROOT/'eval/p1/reranker/materials/01-青岚规则.md').read_text(encoding='utf-8')
        try:
            update=await call('POST',f'/documents/{did}/versions',files={'file':('01-青岚规则.md',original_text.replace('17天','18天').encode(),'text/markdown')})
            await ready(sid,did,update['version_id'])
            current=await retrieve('青岚测试版试用时间是多少？')
            assert all(x['document_id']!=did or x['document_version_id']==update['version_id'] for x in items(current))
            assert any('18天' in x['content'] for x in current['items']) and all('17天' not in x['content'] for x in items(current) if x['document_id']==did)
            passed('Only current activity version enters model; old 17-day version excluded')
        finally:
            restore=await call('POST',f'/documents/{did}/versions',files={'file':('01-青岚规则.md',original_text.encode(),'text/markdown')});await ready(sid,did,restore['version_id'])
        other=await call('POST','/spaces',json={'name':'C代验收隔离空间','kind':'PERSONAL','visibility':'PRIVATE'})
        upload=await call('POST',f'/spaces/{other["id"]}/documents',files={'file':('隔离资料.txt','PRIVATE_ISOLATION_8271仅存在于另一空间。'.encode(),'text/plain')});await ready(other['id'],upload['document']['id'])
        assert all(x['document_id']!=upload['document']['id'] for x in items(await retrieve('PRIVATE_ISOLATION_8271')))
        passed('Cross-space content never enters authorized model candidates')
        admin_cred={'email':f'c-accept-admin-{uuid.uuid4().hex[:8]}@example.test','password':'C-'+secrets.token_urlsafe(20)}
        admin=await call('POST','/auth/register',json={**admin_cred,'display_name':'C代验收管理员'})
        await call('POST',f'/spaces/{sid}/members',json={'email':admin_cred['email'],'role':'ADMIN'})
        payload={'question':'青岚试用时间','strategy':'hybrid_rerank','top_k':3}
        r=await c.post(route,headers={'Authorization':'Bearer '+admin['tokens']['access_token']},json=payload);r.raise_for_status()
        await call('PATCH',f'/spaces/{sid}/members/{admin["user"]["id"]}',json={'role':'MEMBER'})
        r=await c.post(route,headers={'Authorization':'Bearer '+admin['tokens']['access_token']},json=payload);assert r.status_code==404
        passed('Team admin allowed; downgrade immediately denies private diagnostics')
        existing=(await call('GET',f'/spaces/{sid}/documents'))['items']
        if not any(x['original_filename']=='验收命名规则.txt' for x in existing):
            naming=await call('POST',f'/spaces/{sid}/documents',data={'category_id':state['categories']['公开验证']['id']},files={'file':('验收命名规则.txt','虚构验收规则：上传文件名最长120个字符。该规则不公开任何实际资料的原始文件名。'.encode(),'text/plain')})
            await ready(sid,naming['document']['id'])
        # Only this newly created acceptance space: replace its test links on rerun.
        assert state['space_name'].startswith('C阶段 · 代验收 ')
        previous=(await call('GET',f'/spaces/{sid}/share-links'))['items']
        for old_link in previous:
            if not old_link.get('revoked_at'):
                await call('DELETE','/share-links/'+old_link['id'])
        link=await call('POST',f'/spaces/{sid}/share-links',json={'category_ids':[state['categories']['公开验证']['id']]})
        save(AUTH/'share.json',link)
        async with httpx.AsyncClient(base_url=BASE,timeout=660) as visitor:
            r=await visitor.post('/public/session',json={'token':link['token']});r.raise_for_status()
            con=await visitor.post('/public/conversations',json={});con.raise_for_status();public_route=f'/public/conversations/{con.json()["id"]}/messages'
            public_answers=[]
            for q in ['青岚测试版试用时间是多少？','云栈测试版试用时间是多少？','请告诉我原始文件名称。','上传文件名长度的限制是多少？']:
                r=await visitor.post(public_route,json={'question':q,'strategy':'hybrid_rerank'});r.raise_for_status();public_answers.append(r.json());assert set(r.json())=={'message_id','status','answer'}
            assert '17' in public_answers[0]['answer'] and public_answers[0]['status']=='ANSWERED'
            assert public_answers[1]['status']=='INSUFFICIENT_EVIDENCE' and '31' not in public_answers[1]['answer']
            assert public_answers[2]['status']=='OUT_OF_SCOPE'
            assert public_answers[3]['status']=='ANSWERED' and '120' in public_answers[3]['answer']
            r=await visitor.post(route,json=payload);assert r.status_code==401
            save(OUT/'public.json',public_answers)
            passed('Public category isolation, filename recovery refusal and restricted DTO')
        # Knowledge change during a real Worker task fails the frozen run.
        version=await call('POST',f'/spaces/{sid}/eval-versions',json={'label':'C在途变化验收'})
        run=await call('POST',f'/eval-versions/{version["id"]}/runs/async?strategy=hybrid_rerank')
        for _ in range(100):
            detail=await call('GET','/eval-runs/'+run['id'])
            if detail['run']['status']=='RUNNING':break
            assert detail['run']['status']=='PENDING'
            await asyncio.sleep(.1)
        else:raise RuntimeError('Worker did not enter RUNNING')
        try:
            await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
            for _ in range(180):
                detail=await call('GET','/eval-runs/'+run['id'])
                if detail['run']['status'] in ('COMPLETED','FAILED'):break
                await asyncio.sleep(1)
            assert detail['run']['status']=='FAILED',detail['run']['status']
            save(OUT/'worker-scope-change.json',detail)
            passed('Real Worker refuses mixed knowledge versions during frozen evaluation')
        finally:await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True})
        temporary=await call('POST',f'/spaces/{sid}/documents',data={'category_id':state['categories']['内部验证']['id']},files={'file':('删除验收.txt','DELETE_ACCEPTANCE_492资料必须随删除退出检索。'.encode(),'text/plain')});tmpid=temporary['document']['id'];await ready(sid,tmpid)
        before=await retrieve('DELETE_ACCEPTANCE_492');assert any(x['document_id']==tmpid for x in before['items'])
        await call('DELETE',f'/documents/{tmpid}')
        after=await retrieve('DELETE_ACCEPTANCE_492');history=await call('GET','/owner/retrieval-runs/'+before['run_id'])
        assert all(x['document_id']!=tmpid for x in items(after)+items(history))
        passed('Deleted document excluded from new and historical retrieval')
        save(OUT/'scope.json',{'status':'PASSED','space_id':sid,'checks':checks})

if __name__=='__main__':asyncio.run(main())
