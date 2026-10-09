import asyncio,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[3];AUTH=ROOT/'.auth/p1-chunk';OUT=ROOT/'output/p1-chunk'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
async def main():
    state=read(AUTH/'state.json');checks=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:10087/api/v1',timeout=660) as c:
        login=await c.post('/auth/login',json=read(AUTH/'credentials.json'));login.raise_for_status();c.headers['Authorization']='Bearer '+login.json()['tokens']['access_token']
        for fmt,question,filename,literal in [('pdf','青桥试用期限有几天？','01-青桥.pdf','16天'),('md','云港同步异常的代码是什么？','04-云港.md','DQ-404'),('txt','风禾单个文件大小限制是多少？','05-风禾.txt','13MB')]:
            for strategy in ['hybrid','hybrid_rerank']:
                r=await c.post(f"/owner/spaces/{state['spaces'][fmt]['id']}/retrieval-runs",json={'question':question,'strategy':strategy,'top_k':5});r.raise_for_status();data=r.json()
                assert data['strategy']==strategy and data['items'][0]['document_name']==filename
                assert literal in ''.join(data['items'][0]['content'].split())
                if strategy=='hybrid_rerank':assert all(not x['truncated'] for x in data['config_snapshot']['rerank_inputs'])
                checks.append({'format':fmt,'strategy':strategy,'response':data});print('PASS',fmt,strategy,flush=True)
        (OUT/'strategy-check.json').write_text(json.dumps({'status':'PASSED','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':asyncio.run(main())
