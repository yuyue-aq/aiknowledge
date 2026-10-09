"""Independent live D corpus: exact preview spans, real rebuild and retrieval pairs."""
import asyncio,hashlib,json,os,secrets,sys,uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[3];FIX=ROOT/'eval/p1/chunk'
OUT=ROOT/'output/p1-chunk';AUTH=ROOT/'.auth/p1-chunk'
BASE='http://127.0.0.1:10087/api/v1'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def normalized(text):return ''.join(text.split())

async def main():
    manifest=read(FIX/'manifest.json');assert hashlib.sha256((FIX/'cases.json').read_bytes()).hexdigest()==manifest['gold_sha256']
    async with httpx.AsyncClient(base_url=BASE,timeout=660) as c:
        async def call(method,path,**kw):
            r=await c.request(method,path,**kw);r.raise_for_status();return r.json() if r.content else None
        async def ready(sid,did,version=None):
            for _ in range(240):
                docs=(await call('GET',f'/spaces/{sid}/documents'))['items'];d=next(x for x in docs if x['id']==did)
                if d['status']=='FAILED':raise RuntimeError(d.get('failure_code','Upload failed'))
                if d['status']=='READY' and (not version or d['active_version_id']==version):return d
                await asyncio.sleep(1)
            raise RuntimeError('Synthetic processing timeout')
        if sys.argv[1]=='seed':
            if (AUTH/'credentials.json').exists():
                credentials=read(AUTH/'credentials.json');account=await call('POST','/auth/login',json=credentials)
            else:
                credentials={'email':f'd-chunk-{uuid.uuid4().hex[:10]}@example.test','password':'D-'+secrets.token_urlsafe(24)}
                account=await call('POST','/auth/register',json={**credentials,'display_name':'D结构分块验收'})
                save(AUTH/'credentials.json',credentials)
            c.headers['Authorization']='Bearer '+account['tokens']['access_token']
            state=read(AUTH/'state.json') if (AUTH/'state.json').exists() else {'spaces':{}}
            for fmt in ['pdf','md','txt']:
                name='D阶段 · 分块验收 '+fmt.upper()
                if fmt not in state['spaces']:
                    space=await call('POST','/spaces',json={'name':name,'kind':'TEAM','visibility':'PRIVATE'})
                    state['spaces'][fmt]={'id':space['id'],'name':name,'docs':{}};save(AUTH/'state.json',state)
                entry=state['spaces'][fmt]
                for filename,digest in manifest['material_sha256'].items():
                    if not filename.endswith('.'+fmt):continue
                    p=FIX/'materials'/filename;assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
                    existing=(await call('GET',f'/spaces/{entry["id"]}/documents'))['items']
                    old=next((x for x in existing if x['original_filename']==filename),None)
                    if old:did=old['id']
                    else:
                        accepted=await call('POST',f'/spaces/{entry["id"]}/documents',files={'file':(filename,p.read_bytes(),{'pdf':'application/pdf','md':'text/markdown','txt':'text/plain'}[fmt])});did=accepted['document']['id']
                    d=await ready(entry['id'],did)
                    entry['docs'][filename]={'id':d['id'],'version_id':d['active_version_id'],'source_sha256':digest};save(AUTH/'state.json',state)
                print('READY',fmt,len(entry['docs']),flush=True)
            save(OUT/'seed-summary.json',{'status':'PASSED','spaces':state['spaces'],'materials':15})
            return
        login=await call('POST','/auth/login',json=read(AUTH/'credentials.json'));c.headers['Authorization']='Bearer '+login['tokens']['access_token']
        state=read(AUTH/'state.json');cases=read(FIX/'cases.json')
        async def retrieve(case):
            sid=state['spaces'][case['format']]['id']
            return await call('POST',f'/owner/spaces/{sid}/retrieval-runs',json={'question':case['question'],'strategy':'dense','top_k':5})
        async def measured(label):
            rows=[]
            for case in cases:
                run=await retrieve(case)
                target=state['spaces'][case['format']]['docs'][case['document']]['id']
                def coverage(k):
                    body=normalized(' '.join(x['content'] for x in run['items'][:k] if x['document_id']==target))
                    return sum(normalized(x) in body for x in case['evidence_literals'])/len(case['evidence_literals']) if case['evidence_literals'] else None
                rows.append({**case,'retrieval':run,'literal_coverage1':coverage(1),'literal_coverage5':coverage(5)})
                save(OUT/(label+'-retrieval.json'),rows);print(label,case['id'],flush=True)
            return rows
        before=await measured('before')
        from app.services.document_parsing import DocumentParser
        parser=DocumentParser();checks=[]
        for fmt,entry in state['spaces'].items():
            sid=entry['id']
            for filename,meta in entry['docs'].items():
                route=f'/owner/spaces/{sid}/documents/{meta["id"]}'
                config={'strategy':'structure','max_tokens':512,'overlap_characters':240}
                preview=await call('POST',route+'/chunk-preview',json={**config,'limit':50})
                assert preview['source_sha256']==meta['source_sha256'] and preview['document_version_id']==meta['version_id']
                chunks=[]
                for offset in range(0,preview['candidate_total'],50):
                    page=preview if offset==0 else await call('POST',route+'/chunk-preview',json={**config,'offset':offset,'limit':50})
                    assert page['fingerprint']==preview['fingerprint'];chunks+=page['candidate']
                blocks={f'block-{b.ordinal}':b.text for b in parser.parse(filename=filename,content=(FIX/'materials'/filename).read_bytes()).blocks}
                coverage={key:set() for key in blocks}
                for ch in chunks:
                    text=blocks[ch['source_block_id']]
                    assert text[ch['char_start']:ch['char_end']]==ch['content']
                    assert hashlib.sha256(ch['content'].encode()).hexdigest()==ch['content_hash'] and ch['token_count']<=512
                    coverage[ch['source_block_id']].update(range(ch['char_start'],ch['char_end']))
                assert all(coverage[k]==set(range(len(text))) for k,text in blocks.items() if text.strip())
                accepted=await call('POST',route+'/rechunk',json={**config,'expected_version_id':preview['document_version_id'],'fingerprint':preview['fingerprint']})
                assert accepted['processing_enqueued']
                current=await ready(sid,meta['id'],accepted['version_id'])
                post=await call('POST',route+'/chunk-preview',json={**config,'limit':1})
                assert post['source_sha256']==meta['source_sha256'] and post['document_version_id']==accepted['version_id']
                detail=await call('GET',route)
                version=next(x for x in detail['versions'] if x['id']==accepted['version_id'])
                assert version['chunk_config']==preview['candidate_config']
                assert [(x['content'],x['source_block_id'],x['char_start'],x['char_end'],x['token_count']) for x in detail['chunks']]==[(x['content'],x['source_block_id'],x['char_start'],x['char_end'],x['token_count']) for x in chunks]
                checks.append({'document':filename,'before_chunks':preview['current_total'],'after_chunks':preview['candidate_total'],
                    'new_version_id':accepted['version_id'],'exact_span_and_budget':'PASSED','preview_equals_persisted':'PASSED'})
                save(OUT/'rebuild-checks.json',checks);print('REBUILT',filename,preview['current_total'],'->',preview['candidate_total'],flush=True)
        after=await measured('after')
        summary={'status':'PASSED','documents_checked':len(checks),'paired_cases':len(cases),'notes':'Literal evidence coverage, not semantic answer accuracy. MD parser already splits headings; no benefit is presumed.', 'by_split':{}}
        for split in ['tune','holdout']:
            a=[x for x in before if x['split']==split and x['answerable']];b=[x for x in after if x['split']==split and x['answerable']]
            summary['by_split'][split]={'positive':len(a),'before_full_coverage5':sum(x['literal_coverage5']==1 for x in a),'after_full_coverage5':sum(x['literal_coverage5']==1 for x in b)}
        save(OUT/'live-summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
