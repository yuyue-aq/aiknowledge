"""Scores assigned after assistant reviewed all 150 responses against source."""
import json,csv,statistics,math
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/evaluation/20261006-large150-original'
rows=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
runtime=json.loads((OUT/'run-metadata.json').read_text(encoding='utf-8-sig'))
integrity=json.loads((OUT/'source-integrity-check.json').read_text(encoding='utf-8'))
assert len(rows)==150 and len(runtime)==180 and integrity['status']=='PASSED'
assert len({x['base_id'] for x in rows})==50
by_message={x['message_id']:x for x in runtime}
notes={
    'N08-md':(0,'false_refusal','本地Docker Compose部署有记录，却称没有部署方式并拒答。'),
    'N12-md':(1,'omission','未回答知舟的React与TypeScript前端技术，其余角色与仓流信息正确。'),
    'N13-pdf':(0,'false_refusal','两个项目日期均在资料中，却拒答。'),
    'N13-md':(0,'false_refusal','两个项目日期均在资料中，却拒答。'),
    'N13-txt':(1,'omission','只给出项目A日期，缺少项目B日期。'),
    'N14-md':(0,'false_refusal','仓流明确未使用pgvector/Embedding/RAG，但系统拒答。'),
    'N22-md':(1,'omission','列出业务约束和未实现功能，但遗漏已实现的入库、出库、库存查询业务。'),
    'N23-pdf':(1,'omission','纯检索不调用生成模型判断正确，但未完成向量模型、检索与生成三者区分。'),
    'N23-md':(1,'omission','纯检索不调用生成模型判断正确，但未完成三者区分。'),
    'N23-txt':(1,'omission','纯检索不调用生成模型判断正确，但未完成三者区分。'),
    'N24-pdf':(1,'constraint','所求五项用途基本完整，但违反明确指令，增加项目B/pgvector格子。'),
    'N24-md':(1,'constraint_and_omission','增加明确禁止的B/pgvector格子，B的库存事务机制与Redis缓存用途也未完整说明。'),
    'N24-txt':(1,'constraint_and_omission','增加明确禁止的B/pgvector格子，B的库存事务机制与Redis缓存用途未完整说明。'),
    'N25-md':(0,'false_refusal','完整时间线已记录，却只取到实习并拒绝完整概括。'),
    'N27-pdf':(0,'false_refusal','项目起止月份已记录，却拒绝计算自然月数。不是算术算错。'),
    'N27-md':(0,'false_refusal','项目起止月份已记录，却拒绝计算自然月数。'),
    'N37-md':(0,'reference_error','前置顺序为知舟、仓流，但把第二个指为知舟，回答React/TypeScript而非Vue。'),
}
source_checks=0
for row in rows:
    doc=json.loads((OUT/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    by_ordinal={x['ordinal']:x['content'] for x in doc['chunks']}
    chunk_ids={x['chunk_id'] for x in doc['chunks']}
    meta=by_message[row['response']['message_id']]
    assert meta['prompt_version']=='rag-prompt-v2-coverage-grid-audit'
    assert set(meta['retrieved_chunk_ids'])<=chunk_ids
    for citation in row['response']['citations']:
        assert citation.get('source_available',True)
        assert citation['document_name']==doc['document']['original_filename']
        assert citation['quoted_text']==by_ordinal[citation['ordinal']]
        source_checks+=1
    score,issue,note=notes.get(row['id'],(2,'none','必答事实与行为正确，引用支持核心事实或正确拒答。'))
    row['review']={'score':score,'issue':issue,'note':note,'reviewer':'Codex assistant; not independently human verified'}
    row['runtime']=meta
    row['citation_source_match']=True

def stats(values):
    count=Counter(x['review']['score'] for x in values)
    return {'total':len(values),'complete':count[2],'partial':count[1],'incorrect':count[0],
            'strict_pass_rate':count[2]/len(values),'score':sum(x['review']['score'] for x in values),'max_score':2*len(values)}

summary=stats(rows)
summary['by_format']={fmt:stats([x for x in rows if x['format']==fmt]) for fmt in ['pdf','md','txt']}
summary['by_kind']={kind:stats([x for x in rows if x['kind']==kind]) for kind in ['事实','综合','计算','追问','拒答']}
summary['unique_questions']=50
summary['all_three_formats_complete_questions']=sum(all(x['review']['score']==2 for x in rows if x['base_id']==base) for base in {x['base_id'] for x in rows})
summary['false_refusals']=sum(x['review']['issue']=='false_refusal' for x in rows)
summary['reference_errors']=sum(x['review']['issue']=='reference_error' for x in rows)
summary['negative_refusal_status_correct']=sum(not x['answerable'] and x['response']['status']=='INSUFFICIENT_EVIDENCE' for x in rows)
summary['citation_source_checks']=source_checks
summary['source_integrity']='PASSED'
latency=sorted(x['runtime']['latency_ms']/1000 for x in rows)
summary['latency_p50_seconds']=statistics.median(latency)
summary['latency_p95_seconds']=latency[math.ceil(.95*150)-1]
summary['latency_max_seconds']=max(latency)
summary['input_tokens_180_answers']=sum(x['input_tokens'] or 0 for x in runtime)
summary['output_tokens_180_answers']=sum(x['output_tokens'] or 0 for x in runtime)
summary['formal_count']=150
summary['discarded_pilot_count']=150
summary['acceptance_met']=summary['strict_pass_rate']>=.90 and summary['negative_refusal_status_correct']==30
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'reviewed_results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

with (OUT/'逐题评分.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream)
    writer.writerow(['编号','格式','类型','问题','标准答案','实际状态','实际回答','分数0至2','问题类型','审核说明'])
    for row in rows:writer.writerow([row['id'],row['format'],row['kind'],row['question'],row['expected_answer'],row['response']['status'],row['response']['answer'],row['review']['score'],row['review']['issue'],row['review']['note']])

lines=['# V2原版虚构资料150次扩展评测报告','',
    '日期：2026-10-06（Asia/Shanghai）。评分：Codex助手逐题审核，未经过独立人工复核。','',
    '## 结论','',
    '正式150次作答：133次完全通过、9次部分通过、8次错误，严格通过率88.7%。按2/1/0评分为275/300（平均91.7%），但部分通过不计入完整通过率，未达到沿用的90%完整通过目标（至少135/150）。',
    '30次无依据提问均正确拒答；主要风险是有答案题的上下文不足与遗漏、不对称比较违反用户范围、以及一条多轮指代错误。更大新问法样本没有延续旧已知50题的100%，说明旧结果不能被当成泛化保证。','',
    '## 实验设计与完整性','',
    '50个新增问法，每题分别在PDF、MD、TXT空间执行，共150次计分作答。不是150个独立问题，更不是150份独立文档。三个格式是同一份四章节合成档案；配对观察相关，未给出独立样本置信区间。',
    '新增题型：事实10、综合15、计算5、多轮追问10、拒答10。新增问题的完整字符串与旧50题没有重复，但事实语料仍相同、部分语义重合；属于新问法回归，不是陌生语料盲测。',
    '最初150次预跑发现MD为19天/40天，PDF/TXT及原标准为14天/30天，不能公平比较。用户确认统一原版后，新建三个独立私密空间，复制资料并仅在独立MD副本恢复14/30；不覆盖原文件、原空间或其修改。预跑全量保留但不纳入正式统计，不是按回答好坏挑选样本。',
    '正式入库核对三种格式均为14/30，保存版本、片段ID和正文SHA-256。每个问题组三种格式开始前检查三份资料，结束后再次检查，内容/版本指纹一致。生产代码、模型和提示词在正式150次中保持不变，没有边测边修或重答失败题。',
    '通过真实拥有者问答API逐题执行，每道单轮新建会话；多轮题额外提交前置问题，共180个问答动作。内部协议补全/语义校验属于正常产品流程，用量包含在对应运行记录中。30次前置回答不计入150分数，多轮通过率不是完整会话的每条消息都正确。',
    '测试空间使用无支付的演示PRO配额。预跑旧空间配额已恢复；新评测空间初始设为PRO用于复现，测试结束恢复到其记录的初始配额。没有修改其他用户空间、开放分类或真实资料。','',
    '## 按格式配对结果','',
    '| 格式 | 完全通过 | 部分通过 | 错误 | 严格通过率 |','|---|---|---|---|---|',
]
for fmt,s in summary['by_format'].items():lines.append(f'| {fmt.upper()} | {s["complete"]}/50 | {s["partial"]} | {s["incorrect"]} | {s["strict_pass_rate"]:.1%} |')
lines+=['', '50个新问题中，40个在三种格式上均完全通过。这里仅比较本软件对这一份合成语料的处理，不能推广为所有Markdown都比PDF或TXT差。Markdown有26个片段，PDF/TXT各7个片段；最终生成上下文上限为4个，分块粒度与选择策略是重要变量。','',
    '## 按题型结果','', '| 类型 | 完全通过 | 部分通过 | 错误 |','|---|---|---|---|']
for kind,s in summary['by_kind'].items():lines.append(f'| {kind} | {s["complete"]}/{s["total"]} | {s["partial"]} | {s["incorrect"]} |')
lines+=['', '## 问题定位与优先级','',
    '1. P1：跨章节证据召回与上下文覆盖。7次有答案题被拒答，包括部署方式、两个项目日期、排除的检索能力、时间线与自然月计算。N08-md、N13-pdf/md的目标事实在候选中已找到，但只读重构最终4个片段时没有进入上下文；N25-md的教育日期在候选中却未选入，项目日期则在候选层就缺失。应拆分多事实查询、同权限范围补召回并扩展相关章节/邻近片段，再检查必答事实覆盖；不要用取消拒答来掩盖证据不足。',
    '2. P1：不对称比较的范围约束。N24明确要求A三项、B两项且禁止B/pgvector，程序仍生成六格；三个格式都违反了范围约束，MD/TXT还遗漏B组件的具体职责。覆盖矩阵必须来自各对象实际被要求的属性，不能直接做所有对象×所有组件的笛卡尔积。',
    '3. P1：多轮指代。N37-md前置顺序是知舟、仓流，追问“第二个的前端”却返回知舟React/TypeScript。运行记录中的改写问题仍是原追问，没有附带前轮上下文。应支持第二个、后者等指代并保持实体顺序；历史只用于理解对象，事实仍从当前有权限的资料获取。',
    '4. P2：普通多要求覆盖。N12-md遗漏A前端，N13-txt遗漏B日期，N22-md遗漏已实现业务，N23三个格式只答纯检索是否生成而没有区分三者。不能只对显式英文组件比较题检查完整性。','',
    '## 引用与诊断方法','',
    f'183条返回引用逐条比对对应空间的当前文档片段、文件名和可用状态，均一致；所有候选片段ID属于其目标测试文档。这是来源一致性，不是183条引用都语义正确：N37-md引用确实来自A前端，却错误回答B。',
    '拒答和缺失问题的上下文诊断，是用保存的候选顺序及未变的lexical-dense-v1算法只读重构，不冒充原始提示词日志。该重排按词面分数与密集排名混合，不依赖原浮点值；本轮阈值为None。详情在context-selection-diagnostics.json。',
    '每个空间只有一份文档，文档级命中容易达到100%，不能反映多项必答事实是否进入最终上下文。未完整标注每题原文区间，因此不报告证据Recall或原子事实覆盖率。',
    '没有发现30道无依据题编造具体未知值。7次错误拒答及1次指代错误仍是端到端失败，不能因为HTTP成功或引用真实就判通过。','',
    '## 性能与用量','',
    f'150个计分响应的后端执行P50={summary["latency_p50_seconds"]:.2f}秒，P95={summary["latency_p95_seconds"]:.2f}秒，最大={summary["latency_max_seconds"]:.2f}秒。顺序执行、模型已预热，没有并发压力测试或新冷启动验收。',
    f'正式180次问答记录的输入token={summary["input_tokens_180_answers"]}，输出token={summary["output_tokens_180_answers"]}，含正常内部重试/语义核验的成功返回用量，不含弃用的预跑或之前测试。没有估算未核实价格下的费用。',
    '本轮不替代公开访客隔离、团队越权、资料停用/更新或生产部署验收；题目中答对权限规则，不代表程序门禁已实测。','',
    '## 评分标准','',
    '- 2：所问事实完整、正确，遵循范围，行为状态合理且引用支持核心事实。',
    '- 1：核心正确但有遗漏或违反明确范围；部分事实有依据并明确缺失，不当成完整通过。',
    '- 0：事实归属错误、编造或有依据而整体拒答。N27错误是拒答，未发现45个月等算术算错。',
    '下一步应先修上述三项P1，再复跑本集；另留未用于调参的新问法/新文档，避免继续只优化已知题。','',
    '## 逐题记录','',
]
for row in rows:
    lines+=['### '+row['id']+' '+row['question'],'']
    if row.get('setup_question'):lines+=['前置问题：'+row['setup_question'],'']
    lines+=['标准答案：'+row['expected_answer'],'','实际回答：'+row['response']['answer'],'',
            '状态：'+row['response']['status']+'；得分：'+str(row['review']['score'])+'/2；'+row['review']['note'],'']
(OUT/'150次扩展评测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
