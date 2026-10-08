"""Run frozen 500 cases against the real owner API, one request per space."""
import os
import asyncio
import hashlib
import json
import sys
import shutil
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/p1-reranker/500'
MODE=sys.argv[1]
assert MODE in ('hybrid_rerank',)
OUT=BASE/MODE
assert OUT.resolve().is_relative_to(BASE.resolve())
OUT.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
archive=ROOT/'eval/v2/releases/V2.0'
for filename in ['gold_cases.json','dataset-manifest.json']:
    if not (BASE/filename).exists():shutil.copyfile(archive/filename,BASE/filename)
cases=read(BASE/'gold_cases.json')
assert len(cases)==500
assert hashlib.sha256((BASE/'gold_cases.json').read_text(encoding='utf-8').encode()).hexdigest()==read(BASE/'dataset-manifest.json')['gold_sha256']
save(OUT/'gold_cases.json',cases)
state_path=BASE/'state.json'
state=read(state_path) if state_path.exists() else read(ROOT/'output/p1-rrf/500/state.json')
save(state_path,state)
results=read(OUT/'results.json') if (OUT/'results.json').exists() else []
def fingerprint(doc):
    return hashlib.sha256(json.dumps({'version':doc['document']['active_version_id'],'chunks':[(c['chunk_id'],hashlib.sha256(c['content'].encode()).hexdigest()) for c in doc['chunks']]},sort_keys=True).encode()).hexdigest()

async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as client:
        async def login():
            r=await client.post('/auth/login',json=read(ROOT/'.auth/p1-rrf/credentials.json'))
            r.raise_for_status();client.headers['Authorization']='Bearer '+r.json()['tokens']['access_token']
        await login()
        async def call(method,path,**kwargs):
            r=await client.request(method,path,**kwargs)
            if r.status_code==401:await login();r=await client.request(method,path,**kwargs)
            r.raise_for_status();return r.json() if r.content else None
        for fmt in ['pdf','md','txt']:
            if fmt not in state:
                s=await call('POST','/spaces',json={'name':f'P1-RRF-500对照-{fmt.upper()}-20261007','kind':'PERSONAL','visibility':'PRIVATE'})
                state[fmt]={'space_id':s['id'],'initial_plan':s['plan']};save(state_path,state)
        plans={}
        try:
            for fmt,meta in state.items():
                s=await call('GET','/spaces/'+meta['space_id']);plans[fmt]=meta['initial_plan']
                save(OUT/'original-plans.json',plans)
                await call('PATCH','/spaces/'+meta['space_id'],json={'plan':'PRO'})
                if 'document_id' not in meta:
                    p=archive/f'materials/01-项目档案-v1.{fmt}'
                    with p.open('rb') as f:
                        upload=await call('POST','/spaces/'+meta['space_id']+'/documents',files={'file':(p.name,f,{'pdf':'application/pdf','md':'text/markdown','txt':'text/plain'}[fmt])})
                    meta['document_id']=upload['document']['id'];save(state_path,state)
                for attempt in range(120):
                    docs=await call('GET','/spaces/'+meta['space_id']+'/documents')
                    d=next(x for x in docs['items'] if x['id']==meta['document_id'])
                    if d['status']=='FAILED':raise RuntimeError('Synthetic document processing failed')
                    if d['status']=='READY':break
                    await asyncio.sleep(5)
                else:raise RuntimeError('Document processing timeout')
                d=await call('GET',f"/owner/spaces/{meta['space_id']}/documents/{meta['document_id']}")
                text=''.join(c['content'] for c in d['chunks']).replace(' ','').replace('\n','')
                assert '知识库试用期为14天' in text and '资料保留周期为30天' in text
                save(OUT/f'document-{fmt}.json',d)
            manifest={f:fingerprint(read(OUT/f'document-{f}.json')) for f in state}
            save(OUT/'source-manifest.json',manifest)
            done={x['id'] for x in results}
            async def run_format(fmt):
                meta=state[fmt]
                for case in cases:
                    if case['format']!=fmt or case['id'] in done:continue
                    d=await call('GET',f"/owner/spaces/{meta['space_id']}/documents/{meta['document_id']}")
                    assert fingerprint(d)==manifest[fmt], 'Source changed'
                    setup=None
                    try:
                        conversation=await call('POST','/owner/conversations',json={'space_id':meta['space_id'],'title':case['id']+' '+OUT.name})
                        route='/owner/conversations/'+conversation['id']+'/messages'
                        if case.get('setup_question'):setup=await call('POST',route,json={'question':case['setup_question'],'stream':False,'strategy':MODE})
                        answer=await call('POST',route,json={'question':case['question'],'stream':False,'strategy':MODE})
                        item={**case,'conversation_id':conversation['id'],'response':answer,'setup_response':setup}
                    except (httpx.HTTPError,ValueError) as error:
                        item={**case,'response':{'status':'HTTP_ERROR','answer':type(error).__name__,'citations':[]},'setup_response':setup}
                    results.append(item)
                    save(OUT/'results.json',sorted(results,key=lambda x:x['id']))
                    print(len(results),case['id'],fmt,item['response']['status'],flush=True)
            # Gather all task outcomes before restoring plans, even on source failure.
            tasks=await asyncio.gather(*(run_format(f) for f in state),return_exceptions=True)
            for result in tasks:
                if isinstance(result,BaseException):raise result
            for f,m in state.items():
                d=await call('GET',f"/owner/spaces/{m['space_id']}/documents/{m['document_id']}")
                assert fingerprint(d)==manifest[f]
            save(OUT/'source-integrity-check.json',{'status':'PASSED','checked_cases':len(results),'fingerprints':manifest,'original_14_30':True})
            print('FINISHED',len(results),flush=True)
        finally:
            for f,plan in plans.items():
                await call('PATCH','/spaces/'+state[f]['space_id'],json={'plan':plan})
            print('Synthetic space plans restored',flush=True)
if __name__=='__main__':asyncio.run(main())
