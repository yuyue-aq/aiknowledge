"""Resume real P1 checks using the existing synthetic account; no auth overwrite."""
import asyncio,json,os
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-rrf'

async def main():
    auth=json.loads((ROOT/'.auth/p1-rrf/credentials.json').read_text(encoding='utf-8'))
    rows=json.loads((OUT/'retrieval-comparison.json').read_text(encoding='utf-8'))
    sid=rows[0]['results']['hybrid']['response']['space_id']
    checks=[]
    async with httpx.AsyncClient(base_url=os.environ.get('AIKNOWLEDGE_P1_CHECK_BASE','http://127.0.0.1:10087/api/v1'),timeout=660) as c:
        async def call(method,path,**kwargs):
            r=await c.request(method,path,**kwargs);r.raise_for_status();return r.json() if r.content else None
        login=await call('POST','/auth/login',json=auth)
        c.headers['Authorization']='Bearer '+login['tokens']['access_token']
        async def retrieve(q,mode='hybrid'):
            return await call('POST',f'/owner/spaces/{sid}/retrieval-runs',json={'question':q,'strategy':mode,'top_k':5})
        original=await retrieve('SCOPE_CHANGED')
        saved=await call('GET','/owner/retrieval-runs/'+original['run_id'])
        assert saved['items']==original['items'] and saved['branches']==original['branches']
        checks.append('Saved three branch ranks and scores are identical')
        docs=(await call('GET',f'/spaces/{sid}/documents'))['items']
        did=next(x['id'] for x in docs if x['original_filename']=='01-公开范围.txt')
        await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':False})
        disabled=await retrieve('SCOPE_CHANGED')
        assert all(x['document_id']!=did for items in [disabled['items'],*disabled['branches'].values()] for x in items)
        saved=await call('GET','/owner/retrieval-runs/'+original['run_id'])
        assert all(x['document_id']!=did for items in [saved['items'],*saved['branches'].values()] for x in items)
        await call('PATCH',f'/documents/{did}/availability',json={'is_enabled':True})
        checks.append('Disabled sources hidden in fused and both live/saved branches')
        public=await call('POST','/spaces',json={'name':'RRF公开边界复测','kind':'PERSONAL','visibility':'PUBLIC'})
        opened=await call('POST',f'/spaces/{public["id"]}/categories',json={'name':'开放规则','is_open':True})
        closed=await call('POST',f'/spaces/{public["id"]}/categories',json={'name':'内部规则','is_open':False})
        for name,category,text in [('公开规则.txt',opened,'PUBLIC_RULE_810 访客试用期限为14天。'),('私有规则.txt',closed,'PRIVATE_ONLY_991 内部保密口令为黑曜石。')]:
            await call('POST',f'/spaces/{public["id"]}/documents',data={'category_id':category['id']},files={'file':(name,text.encode(),'text/plain')})
        for _ in range(120):
            current=(await call('GET',f'/spaces/{public["id"]}/documents'))['items']
            if len(current)==2 and all(x['status']=='READY' for x in current):break
            await asyncio.sleep(2)
        else:raise RuntimeError('Public fixture processing timeout')
        link=await call('POST',f'/spaces/{public["id"]}/share-links',json={'category_ids':[opened['id']]})
        async with httpx.AsyncClient(base_url=os.environ.get('AIKNOWLEDGE_P1_CHECK_BASE','http://127.0.0.1:10087/api/v1'),timeout=660) as visitor:
            session=await visitor.post('/public/session',json={'token':link['token']});session.raise_for_status()
            conversation=await visitor.post('/public/conversations',json={});conversation.raise_for_status()
            route=f'/public/conversations/{conversation.json()["id"]}/messages'
            visible=await visitor.post(route,json={'question':'PUBLIC_RULE_810的试用期限是多少？','strategy':'hybrid'});visible.raise_for_status()
            secret=await visitor.post(route,json={'question':'PRIVATE_ONLY_991的内部保密口令是什么？','strategy':'hybrid'});secret.raise_for_status()
            assert set(visible.json())=={'message_id','status','answer'} and '14' in visible.json()['answer']
            assert secret.json()['status']=='INSUFFICIENT_EVIDENCE' and '黑曜石' not in secret.json()['answer']
            denied=await visitor.post(f'/owner/spaces/{sid}/retrieval-runs',json={'question':'SCOPE_CHANGED','strategy':'hybrid'})
            assert denied.status_code==401
            (OUT/'public-check.json').write_text(json.dumps({'status':'PASSED','visible_answer':visible.json(),'private_answer':secret.json()},ensure_ascii=False,indent=2),encoding='utf-8')
        checks.extend(['Public hybrid answers open category facts','Closed-category secret is refused','Public DTO contains no raw source or ranks','Visitor diagnostics denied'])
        case=await call('POST',f'/spaces/{sid}/eval-cases',json={'question':'v2.7.4是什么接口版本？','expected_answer':'公开范围产品的接口版本。','scope':'OWNER','expected_document_ids':[did],'category_ids':[]})
        version=await call('POST',f'/spaces/{sid}/eval-versions',json={'label':'RRF冻结验收','case_ids':[case['id']]})
        evals={}
        for mode in ['dense','hybrid']:
            run=await call('POST',f'/eval-versions/{version["id"]}/runs/async?strategy={mode}')
            for _ in range(180):
                detail=await call('GET','/eval-runs/'+run['id'])
                if detail['run']['status'] in ['COMPLETED','FAILED']:break
                await asyncio.sleep(2)
            assert detail['run']['status']=='COMPLETED', detail['run'].get('failure_code')
            assert detail['run']['retrieval_config_snapshot']['retrieval_strategy']==mode
            assert detail['results'][0]['execution_snapshot']['retrieval_strategy']==mode
            evals[mode]=detail
        checks.append('Real queued Worker uses each frozen evaluation strategy')
        (OUT/'worker-check.json').write_text(json.dumps(evals,ensure_ascii=False,indent=2),encoding='utf-8')
        (OUT/'runtime-check.json').write_text(json.dumps({'status':'PASSED','space_id':sid,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Runtime checks PASSED',len(checks),flush=True)

if __name__=='__main__':asyncio.run(main())
