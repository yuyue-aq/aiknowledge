import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/evaluation/20261006'
results=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
metadata=json.loads((OUT/'run-metadata.json').read_text(encoding='utf-8-sig'))
by_message={x['message_id']:x for x in metadata}
assert len(results)==50 and len(metadata)==55
notes={
    'Q23':(1,'只复述项目总览，未具体覆盖A的个人学习资料整理目标及B的入库、出库、库存查询和审计业务。'),
    'Q24':(1,'A的存储和异步任务、B的Redis缓存说明正确，但B的PostgreSQL库存事务用途未明确回答。'),
    'Q28':(0,'错误声称项目A未记录指标，同时给出0.86和0.90，构成矛盾。原文将这些指标记在项目A章节下。'),
}
for case_id in ['Q43','Q47','Q48','Q49','Q50']:
    notes[case_id]=(1,'文字正确说明资料未提供，没有编造；但status返回ANSWERED，拒答状态应为INSUFFICIENT_EVIDENCE。')

provenance=[]
for row in results:
    doc=json.loads((OUT/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    chunks={x['ordinal']:x['content'] for x in doc['chunks']}
    citations=row['response']['citations']
    match=all(c.get('source_available',True) and c['quoted_text']==chunks.get(c['ordinal']) and c['document_name']==doc['document']['original_filename'] for c in citations)
    assert match,row['id']
    row['review']={'score':notes.get(row['id'],(2,''))[0],
                  'note':notes.get(row['id'],(2,'事实完整、状态符合预期；所需引用支持回答，或正确拒答。'))[1],
                  'reviewer':'Codex assistant; not independently human verified',
                  'citation_source_match':match,
                  'citation_ordinals':[c['ordinal'] for c in citations]}
    meta=by_message[row['response']['message_id']]
    row['runtime']=meta
    row['document_hit_at_12']=bool(set(meta['retrieved_chunk_ids']) & {c['chunk_id'] for c in doc['chunks']})
    if row['answerable']: assert citations,row['id']

counts=Counter(x['review']['score'] for x in results)
latency=sorted(x['runtime']['latency_ms']/1000 for x in results)
answerable=[x for x in results if x['answerable']]
negative=[x for x in results if not x['answerable']]
metrics={
    'total':50,'complete':counts[2],'partial':counts[1],'incorrect':counts[0],
    'score_out_of_100':sum(x['review']['score'] for x in results),
    'strict_pass_rate':counts[2]/50,
    'text_correct_complete_rate':47/50,
    'refusal_text_correct':10,'refusal_status_correct':sum(x['response']['status']=='INSUFFICIENT_EVIDENCE' for x in negative),
    'document_recall_at_12':sum(x['document_hit_at_12'] for x in answerable)/len(answerable),
    'latency_p50_seconds':statistics.median(latency),'latency_p95_seconds':latency[math.ceil(.95*len(latency))-1],
    'input_tokens_55_answers':sum(x['input_tokens'] or 0 for x in metadata),
    'output_tokens_55_answers':sum(x['output_tokens'] or 0 for x in metadata),
    'transport_completed':50,
    'acceptance_met':counts[2]>=45 and all(x['response']['status']=='INSUFFICIENT_EVIDENCE' for x in negative),
    'citation_source_checks':sum(len(x['response']['citations']) for x in results),
}
(OUT/'reviewed_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'summary.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')

lines=['# V2虚构资料50题评测报告','',
    '评测日期：2026-10-06（Asia/Shanghai）。判定人：Codex助手，未经过用户或独立人工复核。','',
    '本轮结果：42题完全通过，7题部分通过，1题错误，得分91/100。严格通过率84%，未满足“至少45题完全通过、10道拒答题状态全部正确”的验收目标。', '',
    '## 方法与范围','',
    '使用此前生成的林知远虚构档案v1，分别在三个全新私密个人空间上传PDF、MD和TXT，每个空间仅一份文档。标准答案没有上传。',
    '通过当前Docker V2的真实拥有者问答API逐题执行，使用DeepSeek Flash与本地BGE。50个计分问题另有5次多轮前置问答，合计55次问答。不是内置评测页面的批量运行；原始响应、原文引用与后端运行记录均保存在附件JSON。',
    '题型：事实20、综合10、计算5、多轮5、拒答10。格式分配：PDF17、MD17、TXT16；各格式题目不同，不能据此比较格式优劣。每道单轮题新建会话，多轮题只使用自然前置问题，没有在追问中附带答案。',
    '本轮为已知合成语料回归，包含此前用来定位问题的题目，不属于盲测或未见过的保留集。所有空间均为私密；本轮未测真实公开分享、团队越权、停用、版本更新或生产部署。', '',
    '## 指标','',
    '| 指标 | 结果 |','|---|---|',
    '| 完整通过（内容、状态与引用） | 42/50，84% |',
    '| 部分通过 / 错误 | 7 / 1 |',
    '| 总分 | 91/100 |',
    '| 仅按文字事实完整性 | 47/50，94%（忽略5条拒答状态错误） |',
    '| 无依据题文字拒答 | 10/10 |',
    '| 无依据题状态正确 | 5/10 |',
    '| 计算 / 多轮追问 | 5/5 / 5/5 |',
    '| 正式问题请求完成 | 50/50 |',
    '| 有答案题文档Recall@12 | '+str(round(metrics['document_recall_at_12']*100,2))+'% |',
    '| 引用原文一致性核对 | '+str(metrics['citation_source_checks'])+'条全部匹配当前文档片段 |',
    '| 后端执行耗时P50 / P95 | '+str(round(metrics['latency_p50_seconds'],2))+'秒 / '+str(round(metrics['latency_p95_seconds'],2))+'秒 |',
    '| 55次问答的输入 / 输出token | '+str(metrics['input_tokens_55_answers'])+' / '+str(metrics['output_tokens_55_answers'])+' |','',
    '文档Recall@12来自真实候选记录、以40道有答案题的目标文档为标注。每个空间只有一份文档，因此这是粗粒度指标；即使命中文档，也可能没有把关键片段传给生成模型。未标注全部来源区间，不能报告片段级Recall、Context Recall或原子事实覆盖率。',
    '所有实际返回的引用均核对了原文片段来源；来源一致不等于每一句回答都受支持，Q28的矛盾表述就是反例。拒答结果没有引用时不计入引用一致性分母。',
    '耗时为后端记录的问答执行时间，不包括文档入库、前端展示或单独的检索冷启动验收。token统计含5次前置回答，不含早前测试或上传处理；没有按未核实的单价估算费用。', '',
    '## 评分标准','',
    '- 2分：必答事实完整、无事实错误，行为状态正确，引用支持核心事实；拒答题正确拒答。',
    '- 1分：核心事实正确但有遗漏，或拒答文字正确而状态错误。',
    '- 0分：事实错误、矛盾表述、编造或严重越权。', '',
    '## 发现的问题与优先级','',
    '1. P1：拒答状态与文字不一致（Q43、Q47、Q48、Q49、Q50）。五题未编造，但ANSWERED状态会让界面和自动指标误判为成功回答。需要区分“回答未记录哪些内容”与“索取未提供的事实”，改善结构化行为判定；不能简单看到“未提供”就用正则改状态。',
    '2. P1：丢失章节归属或模型未正确关联（Q28）。项目A指标数字有引用，但模型错误声称未记录项目A指标。需要保留片段的父级标题、项目归属，检查生成上下文，并增加事实一致性回归。',
    '3. P2：综合题只给概述（Q23、Q24）。补充子问题覆盖检查，明确项目目标和各存储组件职责，不能以笼统概述代替全部要求。',
    '本轮没有修改产品代码或依据测评结果重新调参。修复后应复跑固定题集，再另设未使用过的保留题，避免只对这些已知问法有效。', '',
    '## 逐题评分','',
    '| 编号 | 题型 | 格式 | 分数 | 状态 | 判定 |','|---|---|---|---|---|---|',
]
for row in results:
    lines.append('| '+row['id']+' | '+row['kind']+' | '+row['format'].upper()+' | '+str(row['review']['score'])+' | '+row['response']['status']+' | '+row['review']['note']+' |')
lines += ['', '## 完整题目、标准答案与实际回答','']
for row in results:
    lines += ['### '+row['id']+' '+row['question'],'']
    if row.get('setup_question'):lines+=['前置问题：'+row['setup_question'],'']
    lines += ['标准答案：'+row['expected_answer'],'','实际回答：'+row['response']['answer'],'',
              '得分：'+str(row['review']['score'])+'/2。'+row['review']['note'],
              '引用：'+(', '.join('片段'+str(c['ordinal'])+(('，第'+str(c['page_number'])+'页') if c['page_number'] else '') for c in row['response']['citations']) or '无'), '']
(OUT/'V2虚构资料50题评测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(metrics,ensure_ascii=False))
