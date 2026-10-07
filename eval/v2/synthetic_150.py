"""50 new questions, paired across three formats: 150 scored responses."""
import os
import asyncio,json,sys,hashlib,re,shutil
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/(sys.argv[1] if len(sys.argv)>1 else 'output/evaluation/20261006-large150')
assert OUT.resolve().is_relative_to(ROOT.resolve())
OUT.mkdir(parents=True,exist_ok=True)
SINGLE=[
('事实','档案列出的正式项目经历共有几项？请给出名称。','两项：知舟私有知识库、仓流库存管理。'),
('事实','仓流库存管理面向哪家仓库，属于什么业务？','虚构的晨星文具仓库；文具库存管理业务。'),
('事实','这份资料选择了哪款中文向量模型？输出有多少维？','BAAI/bge-large-zh-v1.5，1024维。'),
('事实','在知舟项目中，Redis承担保存向量的任务吗？','不是；Redis管理异步任务，pgvector保存向量。'),
('事实','蓝色笔记本第一次出库之前，库存是多少？','120本。'),
('事实','档案中的分块长度以什么单位计算，相邻片段重叠多少？','汉字；目标400至700个汉字，重叠80个汉字。'),
('事实','知舟项目在做向量相似度排序以前，先限定哪些范围？','先限定空间与资料状态，再相似度排序。'),
('事实','档案明确记录的是哪种部署方式？有给出真实公网地址吗？','Docker Compose本地部署；未记录真实公网地址，不推断从未部署过。'),
('事实','教育信息写的学位类型和毕业设计题目分别是什么？','工学学士；课程资料检索助手。'),
('事实','试用期与资料保留周期属于哪个版本的测试事实？分别几天？','版本1.0，14天、30天，是虚构测试事实。'),
('综合','请仅对比两个项目中Redis各自的具体职责，不介绍其他技术。','A异步任务，B热点库存查询缓存；不展开无关技术。'),
('综合','不使用项目简称，比较知舟私有知识库与仓流库存管理的前端技术和林知远职责。','知舟React/TypeScript、独立开发负责前后端测试部署；仓流Vue由他人开发，林为后端负责库存接口并发控制。'),
('综合','按时间先后列出两个项目的起止月份，不要只答一个项目。','A2026年3月至6月；B2026年7月至9月。'),
('综合','知舟有哪些检索相关能力在仓流项目中被明确排除？','A使用Embedding、pgvector、RAG；B明确没有使用这三者。'),
('综合','按顺序解释仓流出库操作，再分别说明重复请求与库存不足如何处理。','锁记录、检查、扣减、写审计；同一幂等键不重扣；不足报业务错误并事务回滚。'),
('综合','团队拥有者和管理员共同能做什么？哪些操作由拥有者独占？','共同管理资料、引用、检索与评测；成员管理、拥有权转移、删除空间、公开分享由拥有者执行。'),
('综合','分享范围内的资料被停用后，访客还能用它回答吗？链接撤销后旧窗口还能继续提问吗？','都不能；必须是授权且启用资料，撤销后不能继续提问。'),
('综合','旧会话回答还看得到，是否说明旧资料仍可作为新答案依据？新版本生效后应使用哪份资料？','旧回答不能证明旧资料仍可用；使用已生效新版本。'),
('综合','资料中的检索指标和答案正确率各是多少，能据此评价当前知溯系统吗？','0.86、0.90，虚构示例，不是当前系统实测成绩。'),
('综合','资料不足和根据原文数字进行计算，分别应如何处理？','不足明确说明、不编造；可计算，但标明是推算而非原文记录。'),
('综合','所有者与团队管理员是同一种角色吗？请说明权限区别。','不是；管理员有知识库管理权限，拥有者还独占成员、转移、删除与公开分享。'),
('综合','仓流有哪些已经实现和明确未实现的业务？请分别列出。','已入库、出库、查询、审计；未实现支付、配送、财务对账、跨仓调拨。'),
('综合','区分向量模型、检索与答案生成：纯检索测试会调用生成模型吗？','向量模型编码，检索找片段，回答依据证据生成；纯检索不调用生成模型，不凭实际配置补写供应商。'),
('综合','比较项目A与B：A只解释PostgreSQL、pgvector、Redis三项；B只解释PostgreSQL、Redis两项。不要增加B的pgvector项。','A业务数据、向量、异步任务；B库存事务与行级锁、热点缓存。仅列指定五项。'),
('综合','按教育、实习、两个项目开发的先后顺序概括经历，保留各段起止年月。','教育2021.9-2025.6；实习2025.7-2026.2；A2026.3-6；B2026.7-9。'),
('计算','按年月差计算、不考虑具体日，2021年9月到2025年6月相隔多少个月？','45个月。不是把起止月都计入的46个月。'),
('计算','包括起止月，两个项目各覆盖几个自然月，合计几个？','A4个月，B3个月，共7个月。'),
('计算','200份文档和50道问题的数量比，化为最简比是多少？','4:1；不代表每题相关文档数。'),
('计算','14天试用期换算为周是多少？','2周；属于示例试用事实。'),
('计算','出库35本后要让100本出库请求有足够库存，至少需补多少本？','剩85本，至少补15本；是数字推算。'),
]
FOLLOW=[
('介绍知舟私有知识库的技术方案。','它用什么保存向量？','pgvector。'),
('介绍仓流库存管理的技术方案。','那个项目用了向量数据库吗？','没有使用pgvector/Embedding/RAG。'),
('介绍资料所述的团队管理员权限。','那成员管理也归他们吗？','不归管理员，归拥有者。'),
('介绍资料中的试用期规则。','这个试用期换算成周是多少？','14天即2周。'),
('解释蓝色笔记本从120本成功出库35本的例子。','重复这次操作后还剩多少？','同一幂等请求不重扣，仍85本。'),
('介绍知舟项目的分块策略。','相邻片段重叠多少汉字？','80个汉字。'),
('按知舟、仓流的顺序介绍两个项目的技术。','第二个的前端用了什么？','仓流由另一位成员用Vue开发。'),
('按知舟、仓流的顺序介绍林知远在两个项目中的角色。','后者是独立开发吗？','后者仓流为团队后端开发者，不是A的独立开发者。'),
('概括档案里明确未记录的个人与实习信息。','主管姓名也没写吗？','是，主管姓名未记录；这是元信息问题，可以ANSWERED。'),
('介绍知舟项目的测试结果。','这些成绩是真实项目的实测成果吗？','不是，虚构示例，不能当成当前知溯实测结果。'),
]
NEGATIVE=[
('把林知远的个人邮箱地址给我。','资料未提供邮箱。'),
('林知远是哪年哪月哪日出生的？','未记录出生日期，不得从入学年推测。'),
('林知远本科GPA是多少？','未提供GPA。'),
('课程资料检索助手的毕业设计导师叫什么？','未记录导师姓名。'),
('知舟项目生产云主机的公网IP是什么？','未记录真实生产主机IP。'),
('档案中的PostgreSQL具体版本号是多少？','未记录版本号。'),
('给出知舟项目最后一次Git提交的精确SHA。','未提供提交SHA，不能读取项目仓库代答。'),
('知舟前端使用的React版本号是多少？','未记录React版本，不得从真实程序配置补答。'),
('请列出仓流项目的真实客户名单。','未记录真实客户名单。'),
('林知远2027年在哪家公司任职？','未记录2027年任职信息。'),
]
base=[]
for kind,question,expected in SINGLE:
    base.append({'question':question,'expected_answer':expected,'kind':kind,'answerable':True})
for setup,question,expected in FOLLOW:
    base.append({'question':question,'setup_question':setup,'expected_answer':expected,'kind':'追问','answerable':True})
for question,expected in NEGATIVE:
    base.append({'question':question,'expected_answer':expected,'kind':'拒答','answerable':False})
assert len(base)==50
old=json.loads((ROOT/'output/evaluation/20261006/gold_cases.json').read_text(encoding='utf-8'))
assert not {x['question'] for x in old}&{x['question'] for x in base}
cases=[{**case,'base_id':f'N{i+1:02d}','id':f'N{i+1:02d}-{fmt}','format':fmt} for i,case in enumerate(base) for fmt in ['pdf','md','txt']]
(OUT/'gold_cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
fresh='--fresh-original' in sys.argv
state_path=OUT/'state.json'
state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else ({} if fresh else json.loads((ROOT/'output/evaluation/20261006-optimized/state.json').read_text(encoding='utf-8')))
state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')


def fingerprint(document):
    value={'version':document['document']['active_version_id'],
           'chunks':[(chunk['chunk_id'],hashlib.sha256(chunk['content'].encode('utf-8')).hexdigest()) for chunk in document['chunks']]}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode('utf-8')).hexdigest()


def save(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


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
                await login();response=await client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        if fresh:
            material_dir=OUT/'unified-materials'
            material_dir.mkdir(exist_ok=True)
            source=ROOT/'output/pdf/V2测试资料'
            for fmt in ['pdf','txt']:
                shutil.copyfile(source/f'01-项目档案-v1.{fmt}',material_dir/f'01-项目档案-v1.{fmt}')
            markdown=(source/'01-项目档案-v1.md').read_text(encoding='utf-8')
            markdown,count_a=re.subn(r'知识库试用期为\s*\d+\s*天','知识库试用期为 14 天',markdown)
            markdown,count_b=re.subn(r'资料保留周期为\s*\d+\s*天','资料保留周期为 30 天',markdown)
            assert count_a==count_b==1
            (material_dir/'01-项目档案-v1.md').write_text(markdown,encoding='utf-8')
            for fmt in ['pdf','md','txt']:
                if fmt not in state:
                    space=await call('POST','/spaces',json={'name':f'V2扩展原版评测-{fmt.upper()}-20261006','kind':'PERSONAL','visibility':'PRIVATE'})
                    state[fmt]={'space_id':space['id']};save('state.json',state)
                    await call('PATCH','/spaces/'+space['id'],json={'plan':'PRO'})
                if 'document_id' not in state[fmt]:
                    path=material_dir/f'01-项目档案-v1.{fmt}'
                    with path.open('rb') as stream:
                        uploaded=await call('POST','/spaces/'+state[fmt]['space_id']+'/documents',files={'file':(path.name,stream,{'pdf':'application/pdf','md':'text/markdown','txt':'text/plain'}[fmt])})
                    state[fmt]['document_id']=uploaded['document']['id'];save('state.json',state)
            print('fresh original materials uploaded',flush=True)
            for fmt,meta in state.items():
                for attempt in range(120):
                    docs=await call('GET','/spaces/'+meta['space_id']+'/documents')
                    doc=next(x for x in docs['items'] if x['id']==meta['document_id'])
                    if doc['status']=='FAILED':raise RuntimeError(doc.get('failure_message'))
                    if doc['status']=='READY':break
                    if attempt%6==0:print(fmt,doc['status'],flush=True)
                    await asyncio.sleep(10)
                else:raise RuntimeError('processing timeout')
        plans_path=OUT/'original-plans.json'
        plans=json.loads(plans_path.read_text()) if plans_path.exists() else {}
        for fmt,meta in state.items():
            space=await call('GET','/spaces/'+meta['space_id'])
            if fmt not in plans:plans[fmt]=space['plan'];save('original-plans.json',plans)
            await call('PATCH','/spaces/'+meta['space_id'],json={'plan':'PRO'})
            doc=await call('GET',f"/owner/spaces/{meta['space_id']}/documents/{meta['document_id']}")
            assert doc['document']['status']=='READY'
            save('document-'+fmt+'.json',doc)
            if fresh:
                text=re.sub(r'\s+','',''.join(chunk['content'] for chunk in doc['chunks']))
                assert '知识库试用期为14天' in text and '资料保留周期为30天' in text,(fmt,'wrong original facts')
        manifest={fmt:fingerprint(json.loads((OUT/('document-'+fmt+'.json')).read_text(encoding='utf-8'))) for fmt in state}
        save('source-manifest.json',manifest)
        result_path=OUT/'results.json'
        results=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else []
        done={x['id'] for x in results}
        try:
            for case in cases:
                if case['id'] in done:continue
                meta=state[case['format']]
                if case['format']=='pdf':
                    for fmt,check in state.items():
                        current=await call('GET',f"/owner/spaces/{check['space_id']}/documents/{check['document_id']}")
                        if fingerprint(current)!=manifest[fmt]:raise RuntimeError('source changed during evaluation')
                setup=None
                try:
                    conversation=await call('POST','/owner/conversations',json={'space_id':meta['space_id'],'title':case['id']+'新样本评测'})
                    route='/owner/conversations/'+conversation['id']+'/messages'
                    if case.get('setup_question'):
                        setup=await call('POST',route,json={'question':case['setup_question'],'stream':False})
                    answer=await call('POST',route,json={'question':case['question'],'stream':False})
                    result={**case,'conversation_id':conversation['id'],'response':answer,'setup_response':setup}
                except (httpx.HTTPError,ValueError) as error:
                    result={**case,'response':{'status':'HTTP_ERROR','answer':str(error),'citations':[]},'setup_response':setup}
                results.append(result);save('results.json',results)
                print(case['id'],result['response']['status'],flush=True)
            print('FINISHED',len(results),flush=True)
            for fmt,meta in state.items():
                current=await call('GET',f"/owner/spaces/{meta['space_id']}/documents/{meta['document_id']}")
                assert fingerprint(current)==manifest[fmt]
            save('source-integrity-check.json',{'status':'PASSED','checked_groups':50,'all_three_formats_original_14_30':fresh,'fingerprints':manifest})
        finally:
            for fmt,plan in plans.items():
                await call('PATCH','/spaces/'+state[fmt]['space_id'],json={'plan':plan})
            print('original test quotas restored',flush=True)


if __name__=='__main__':asyncio.run(main())
