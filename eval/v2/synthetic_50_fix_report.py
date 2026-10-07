import json,statistics,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'output/evaluation/20261006'
OUT=ROOT/'output/evaluation/20261006-final'
rows=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
baseline=json.loads((BASE/'reviewed_results.json').read_text(encoding='utf-8'))
assert len(rows)==50
assert json.loads((BASE/'gold_cases.json').read_text(encoding='utf-8'))==json.loads((OUT/'gold_cases.json').read_text(encoding='utf-8'))
metadata=json.loads((OUT/'run-metadata.json').read_text(encoding='utf-8-sig'))
assert len(metadata)==55
by_message={x['message_id']:x for x in metadata}
source_checks=0
for row in rows:
    doc=json.loads((OUT/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    old_doc=json.loads((BASE/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    assert doc['document']['active_version_id']==old_doc['document']['active_version_id']
    text_by_ordinal={x['ordinal']:x['content'] for x in doc['chunks']}
    for citation in row['response']['citations']:
        assert citation.get('source_available',True)
        assert citation['document_name']==doc['document']['original_filename']
        assert citation['quoted_text']==text_by_ordinal[citation['ordinal']]
        source_checks+=1
    expected='ANSWERED' if row['answerable'] else 'INSUFFICIENT_EVIDENCE'
    assert row['response']['status']==expected,(row['id'],row['response']['status'])
    row['review']={'score':1 if row['id']=='Q24' else 2,
        'note':'A与Redis职责正确，仍未明确说明B中PostgreSQL处理库存事务和行级锁的用途。' if row['id']=='Q24' else '必答事实与状态正确，原文引用支持核心事实或正确拒答。',
        'reviewer':'Codex assistant; not independently human verified',
        'citation_source_match':True}
    row['runtime']=by_message[row['response']['message_id']]
    assert row['runtime']['prompt_version']=='rag-prompt-v2-answerability-context-audit'

latency=sorted(row['runtime']['latency_ms']/1000 for row in rows)
summary={'complete':49,'partial':1,'incorrect':0,'strict_pass_rate':.98,'score':99,
    'refusal_status_correct':10,'backend_tests':358,'citation_source_checks':source_checks,
    'p50_seconds':statistics.median(latency),'p95_seconds':latency[math.ceil(.95*len(latency))-1],
    'maximum_seconds':max(latency),'input_tokens_55_answers':sum(x['input_tokens'] or 0 for x in metadata),
    'output_tokens_55_answers':sum(x['output_tokens'] or 0 for x in metadata),
    'availability_control':'ANSWERED','same_document_versions':True,
    'prompt_version':'rag-prompt-v2-answerability-context-audit'}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'reviewed_results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 拒答状态与项目归属修复复测报告','',
    '日期：2026-10-06（Asia/Shanghai）。逐题判定：Codex助手，未经独立人工复核。','',
    '## 结论','',
    '最终版本在Docker API、worker、beat中生效。原50题完整复跑：49题完全通过、1题部分通过、0题错误，严格通过率98%，得分99/100。10道拒答题均返回INSUFFICIENT_EVIDENCE；项目A指标的错误归属与矛盾表述消失。',
    '本轮满足此前约定的至少45题完全通过和10题拒答状态正确目标，但仅代表这套已知合成回归集；不能据此保证未知资料和所有问法零遗漏。','',
    '## 修复内容','',
    '- 在生成协议中增加布尔can_answer。对于请求具体事实却只说明未提供的回答，规范为资料不足，删除回答引用。',
    '- 第一轮修复仍有Q48、Q49误标，因此增加独立事实值抽取核验。含缺失说明的ANSWERED拟答只触发核验，不按关键词直接改状态：索取具体值而抽取不到值时拒答；询问资料是否记录时可以正常回答。额外模型调用的token用量合并记录；核验失败不会作为正常回答放行。',
    '- 将已存的Markdown/DOCX章节路径从数据库传递给生成上下文。新PDF解析保存明确编号的页首标题；既有PDF从同页首片段恢复标题，限制在同一文档、版本、页码和授权分类的有效片段中。',
    '- 章节路径作为上下文位置参考，正文中的新标题优先；不替换原文，不修改引用文本、页码、原向量或文档版本。已有评测PDF未重新上传。',
    '- 已有PDF恢复只识别明确编号/章标题，不是任意版式、无编号标题或跨页续写的完整结构识别。','',
    '## 验证','',
    '| 项目 | 基线 | 最终复测 |','|---|---|---|',
    '| 完全通过 | 42/50，84% | 49/50，98% |',
    '| 部分通过 | 7 | 1 |',
    '| 错误 | 1 | 0 |',
    '| 得分 | 91/100 | 99/100 |',
    '| 拒答文字正确 | 10/10 | 10/10 |',
    '| 拒答状态正确 | 5/10 | 10/10 |',
    '| 项目A指标归属（Q28） | 矛盾表述 | 正确 |',
    '| 后端自动测试 | 351 | 358 |','',
    '真实API额外对照：“资料是否记录了林知远的电话号码？”返回ANSWERED，说明缺失信息的元信息问题没有被一律误拒答。这条对照不计入50题。另有受控拟答+真实模型核验的三项测试，不能冒充额外端到端题目。',
    f'最终复测后端执行耗时P50={summary["p50_seconds"]:.2f}秒，P95={summary["p95_seconds"]:.2f}秒；最长首题为{summary["maximum_seconds"]:.2f}秒，包含本次缓慢模型冷启动，不能用P95掩盖这一启动等待。冷启动性能尚未在本修复中优化。',
    f'50题与5次多轮前置问答共55个回答，输入token={summary["input_tokens_55_answers"]}、输出token={summary["output_tokens_55_answers"]}。其中包含语义核验消耗，不含早前迭代、额外对照和受控核验调用。未估算未核实单价下的费用。',
    f'{source_checks}条最终引用逐条比对当前版本原文片段，来源均一致。内容与状态逐题核对标准答案；来源一致本身不能证明完整性。','',
    '原测试空间、文档版本、50题标准答案保持一致，PDF/MD/TXT题数为17/17/16。使用真实拥有者问答API，而非内置评测页面批量任务。没有扩展公开分享范围、改动用户资料或使用标准答案作为生成证据。',
    '这是同一已知测试集上的修复回归，没有独立未见过的保留集。公开访客和团队权限本轮没有另做50题评测，已有权限单元回归仍通过。','',
    '## 剩余问题','',
    'Q24仍部分通过：项目B对Redis热点查询缓存的说明正确，但PostgreSQL的库存事务/行级锁职责没有明确回答。它是综合题子问题覆盖不足，不是本轮拒答状态或PDF章节归属错误。建议后续增加子问题覆盖检查，并用未用过的问法验收。','',
    '## 逐题对比','',
    '| 编号 | 类型 | 格式 | 原分数 | 最终分数 | 最终状态 |','|---|---|---|---|---|---|',
]
old={x['id']:x for x in baseline}
for row in rows:
    lines.append('| '+row['id']+' | '+row['kind']+' | '+row['format'].upper()+' | '+str(old[row['id']]['review']['score'])+' | '+str(row['review']['score'])+' | '+row['response']['status']+' |')
lines+=['','## 最终实际回答','']
for row in rows:
    lines+=['### '+row['id']+' '+row['question'],'','标准答案：'+row['expected_answer'],'',
        '实际回答：'+row['response']['answer'],'',
        '判定：'+str(row['review']['score'])+'/2；'+row['review']['note'],'']
(OUT/'拒答状态与项目归属修复复测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
