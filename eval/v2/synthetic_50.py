"""Synthetic end-to-end evaluation through the production owner chat API.

No real user data, secrets, or answer keys are uploaded. Results contain full
answers/citations for separate reviewer grading, never LLM self-scoring.
"""
import os
import asyncio
import json
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / (sys.argv[1] if len(sys.argv)>1 else 'output/evaluation/20261006')
assert OUT.resolve().is_relative_to(ROOT.resolve())
OUT.mkdir(parents=True, exist_ok=True)
MATERIALS = ROOT / 'output/pdf/V2测试资料'

FACTS = [
('林知远的最高学历、专业和毕业时间是什么？','本科；软件工程；2025年6月。'),
('林知远在哪座城市？求职方向是什么？','南京；Python后端开发与RAG应用开发。'),
('林知远在哪里读大学？入学时间是什么？','虚构的江宁信息学院；2021年9月。'),
('林知远的毕业设计叫什么？','课程资料检索助手。'),
('林知远的实习单位、岗位和任职时间是什么？','虚构的青禾软件工作室；后端开发实习生；2025年7月至2026年2月。'),
('知舟私有知识库的项目编号是什么？','PRJ-A。'),
('知舟私有知识库的开发时间是什么？','2026年3月至2026年6月。'),
('林知远在知舟私有知识库中是什么角色？','独立开发者，负责需求、前后端、测试与部署。'),
('知舟私有知识库支持上传哪些文件格式？','PDF、Markdown、TXT。'),
('知舟私有知识库的前后端技术栈是什么？','后端Python与FastAPI；前端React与TypeScript。'),
('知舟私有知识库用什么存储业务数据和向量？','PostgreSQL保存业务数据，pgvector保存向量。'),
('项目A的Embedding模型、向量维度是什么？','BAAI/bge-large-zh-v1.5；1024维。'),
('知舟私有知识库默认Top K是多少？相似度如何衡量？','Top K为5；余弦相似度。'),
('项目A的目标分块长度与重叠长度是多少？','400至700个汉字；重叠80个汉字。'),
('项目A的检索P95是多少？包含冷启动和生成吗？','预热后1.8秒；不包含模型冷启动和答案生成。'),
('项目A的Recall@5是多少？测试规模是多少？','0.86；50道测试题、200份中文文档；均为虚构示例指标。'),
('仓流库存管理的开发时间、团队规模是什么？','2026年7月至2026年9月；3人。'),
('林知远在仓流库存管理中负责什么？','后端库存接口、并发控制、相关后端测试和审计日志；未负责移动端页面。'),
('仓流库存管理的前端是什么？使用了RAG吗？','由另一位成员用Vue开发；没有使用Embedding、pgvector或RAG。'),
('仓流库存管理如何保证库存一致性？','数据库事务和行级锁，先检查后扣减并记录审计；Redis仅用于热点查询缓存。'),
]
COMPOSITE = [
('林知远有哪些项目经历？分别是什么时间开发的？','知舟私有知识库：2026年3-6月；仓流库存管理：2026年7-9月。'),
('比较两个项目中林知远的角色和前端技术。','A独立开发者、React与TypeScript；B后端开发者、Vue由他人开发。'),
('两个项目的目标和主要业务分别是什么？','A个人学习资料整理、有依据问答；B仓库入出库、库存查询和审计。'),
('项目A与B分别如何使用Redis和PostgreSQL？','A：PostgreSQL业务与pgvector向量、Redis异步任务；B：PostgreSQL事务库存、Redis热点查询缓存。'),
('个人空间和团队空间的管理人员结构有什么区别？','个人只有拥有者；团队一个拥有者、多个管理员。'),
('团队管理员能管理评测、原文引用、成员和公开分享吗？','能管理评测、查看引用；成员管理和公开分享由拥有者执行。'),
('库存重复请求和库存不足时分别如何处理？','幂等键避免重复扣减；不足返回业务错误并回滚，库存保持不变。'),
('项目A的Recall@5和人工答案正确率是多少？能代表当前知溯成绩吗？','0.86、0.90；虚构项目示例，不代表当前知溯实测成绩。'),
('资料更新、停用和旧会话回答之间的关系是什么？','新版本生效后使用新版本；停用资料不再参与后续检索问答；旧回答不证明资料仍可用。'),
('公开访客能够使用什么资料？分享撤销后还能提问吗？','仅分享授权范围内启用的资料，不能返回私密资料；撤销后不能继续提问。'),
]
CALC = [
('蓝色笔记本初始120本，成功出库35本后剩多少？','85本。'),
('第一次出库35本占初始120本的百分比是多少？','35/120约29.17%，属于根据原文数字计算。'),
('出库35本后重复同一幂等请求，再尝试出库100本，最终剩多少？','85本；重复不扣减，库存不足失败回滚。'),
('资料保留30天与试用14天相差多少天？','16天，根据版本1.0中的测试事实计算。'),
('200份测试文档、50道测试题，文档数量是题目数量的多少倍？','4倍；虚构测试规模的比例，不是实际每题相关文档数量。'),
]
FOLLOW = [
('介绍知舟私有知识库项目。','其中我负责哪些功能？','项目A：上传、解析、分块、Embedding、检索、引用、停用及空间权限校验。'),
('介绍知舟私有知识库项目。','它是什么时间开发的？','项目A，2026年3月至6月。'),
('介绍仓流库存管理项目。','它的前端是谁用什么技术开发的？','项目B由另一位成员使用Vue开发。'),
('介绍知舟私有知识库项目。','它的检索P95是多少，是否包含生成时间？','项目A预热后1.8秒，不含冷启动和生成。'),
('介绍仓流库存管理项目。','其中是怎么防止重复出库的？','项目B使用唯一幂等键，同一请求重复提交不会重复扣减。'),
]
NEGATIVE = [
('林知远每月工资是多少？','资料未提供工资，不得编造。'),
('林知远的英语六级成绩是多少？','未记录英语考试成绩。'),
('请给出知舟私有知识库的真实公网地址。','未记录真实公网地址。'),
('林知远的家庭住址是什么？','未提供具体家庭住址。'),
('林知远实习时的主管叫什么？','主管姓名未记录。'),
('林知远为什么离开青禾软件工作室？','离职原因未记录。'),
('仓流库存管理的线上营业额是多少？','未记录线上营业额。'),
('仓流库存管理有多少真实客户？','真实客户数量未记录。'),
('林知远2027年开发过什么项目？','未记录2027年项目。'),
('林知远的电话号码是多少？','未提供手机号。'),
]
cases = []
for kind, items in [('事实',FACTS),('综合',COMPOSITE),('计算',CALC),('追问',FOLLOW),('拒答',NEGATIVE)]:
    for item in items:
        entry={'id':f'Q{len(cases)+1:02d}','kind':kind,'format':['pdf','md','txt'][len(cases)%3],
               'question':item[-2], 'expected_answer':item[-1], 'answerable':kind!='拒答'}
        if kind=='追问': entry['setup_question']=item[0]
        cases.append(entry)
assert len(cases)==50
(OUT/'gold_cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')


def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


async def main():
    async with httpx.AsyncClient(base_url='http://localhost:10086/api/v1',timeout=660) as client:
        async def login():
            response=await client.post('/auth/login',json={'email':os.environ['AIKNOWLEDGE_EVAL_EMAIL'],'password':os.environ['AIKNOWLEDGE_EVAL_PASSWORD']})
            response.raise_for_status()
            client.headers['Authorization']='Bearer '+response.json()['tokens']['access_token']
        await login()
        async def call(method,path,**kwargs):
            response=await client.request(method,path,**kwargs)
            if response.status_code==401:
                await login()
                response=await client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        state_path=OUT/'state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        for extension in ['pdf','md','txt']:
            if extension not in state:
                space=await call('POST','/spaces',json={'name':f'V2合成评测-{extension.upper()}-20261006','visibility':'PRIVATE','kind':'PERSONAL'})
                state[extension]={'space_id':space['id']}
                save('state.json',state)
            if 'document_id' not in state[extension]:
                path=MATERIALS/f'01-项目档案-v1.{extension}'
                mime={'pdf':'application/pdf','md':'text/markdown','txt':'text/plain'}[extension]
                with path.open('rb') as stream:
                    result=await call('POST',f"/spaces/{state[extension]['space_id']}/documents",files={'file':(path.name,stream,mime)})
                state[extension]['document_id']=result['document']['id']
                save('state.json',state)
        print('Uploaded three formats',flush=True)
        for extension in ['pdf','md','txt']:
            meta=state[extension]
            for attempt in range(120):
                documents=await call('GET',f"/spaces/{meta['space_id']}/documents")
                document=next(x for x in documents['items'] if x['id']==meta['document_id'])
                if document['status']=='FAILED': raise RuntimeError(document.get('failure_message'))
                if document['status']=='READY': break
                if attempt%6==0: print(extension,document['status'],flush=True)
                await asyncio.sleep(10)
            else: raise RuntimeError('Document processing timeout')
            detail=await call('GET',f"/owner/spaces/{meta['space_id']}/documents/{meta['document_id']}")
            save(f'document-{extension}.json',detail)
            print(extension,'READY',len(detail['chunks']),'chunks',flush=True)
        result_path=OUT/'results.json'
        results=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else []
        completed={x['id'] for x in results}
        for case in cases:
            if case['id'] in completed: continue
            meta=state[case['format']]
            conversation=await call('POST','/owner/conversations',json={'space_id':meta['space_id'],'title':case['id']+'合成评测'})
            route=f"/owner/conversations/{conversation['id']}/messages"
            if case.get('setup_question'):
                setup=await call('POST',route,json={'question':case['setup_question'],'stream':False})
            else: setup=None
            answer=await call('POST',route,json={'question':case['question'],'stream':False})
            result={**case,'conversation_id':conversation['id'],'response':answer,'setup_response':setup}
            results.append(result)
            save('results.json',results)
            print(case['id'],case['format'],answer['status'],answer['answer'],flush=True)
        print('FINISHED',len(results),flush=True)


if __name__=='__main__': asyncio.run(main())
