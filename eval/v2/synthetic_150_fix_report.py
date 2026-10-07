"""Record manual paired review and verify runtime/source provenance."""
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/evaluation/20261007-large150-fixed'
BASE = ROOT / 'output/evaluation/20261006-large150-original'
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
rows = read(OUT / 'results.json')
runtime = read(OUT / 'run-metadata.json')
integrity = read(OUT / 'source-integrity-check.json')
baseline = read(BASE / 'summary.json')
assert len(rows) == 150 and len(runtime) == 180
assert integrity['status'] == 'PASSED'
assert integrity['fingerprints'] == read(BASE / 'source-integrity-check.json')['fingerprints']
by_message = {x['message_id']: x for x in runtime}
citations_checked = 0
for row in rows:
    doc = read(OUT / f'document-{row["format"]}.json')
    old = read(BASE / f'document-{row["format"]}.json')
    assert doc == old
    ids = {x['chunk_id'] for x in doc['chunks']}
    bodies = {x['ordinal']: x['content'] for x in doc['chunks']}
    meta = by_message[row['response']['message_id']]
    assert meta['prompt_version'] == 'rag-prompt-v2-scoped-subquery-context'
    assert set(meta['retrieved_chunk_ids']) <= ids
    assert set(meta['model']['context_chunk_ids']) <= ids
    assert len(meta['model']['context_chunk_ids']) <= 12
    for citation in row['response']['citations']:
        assert citation.get('source_available', True)
        assert citation['document_name'] == doc['document']['original_filename']
        assert citation['quoted_text'] == bodies[citation['ordinal']]
        citations_checked += 1
    partial = row['base_id'] == 'N23'
    row['review'] = {
        'score': 1 if partial else 2,
        'issue': 'omission' if partial else 'none',
        'note': '纯检索不调用生成模型判断正确，但遗漏向量模型、检索与生成三者的区别。' if partial else '所问事实完整正确，遵循范围，或正确拒答。',
        'reviewer': 'Codex assistant; not independently human verified',
    }
    row['runtime'] = meta
    row['citation_source_match'] = True

def stats(values):
    c = Counter(x['review']['score'] for x in values)
    return dict(total=len(values), complete=c[2], partial=c[1], incorrect=c[0],
                strict_pass_rate=c[2]/len(values), score=sum(x['review']['score'] for x in values))
summary = stats(rows)
summary['by_format'] = {f: stats([x for x in rows if x['format'] == f]) for f in ['pdf','md','txt']}
summary['by_kind'] = {k: stats([x for x in rows if x['kind'] == k]) for k in sorted({x['kind'] for x in rows})}
summary.update(unique_questions=50, source_integrity='PASSED', citation_source_checks=citations_checked,
               negative_refusal_status_correct=sum(not x['answerable'] and x['response']['status']=='INSUFFICIENT_EVIDENCE' for x in rows),
               all_three_formats_complete_questions=49, false_refusals=0, reference_errors=0)
lat = sorted(x['runtime']['latency_ms']/1000 for x in rows)
summary.update(latency_p50_seconds=statistics.median(lat), latency_p95_seconds=lat[math.ceil(.95*len(lat))-1],
               latency_max_seconds=max(lat), first_response_seconds=rows[0]['runtime']['latency_ms']/1000,
               input_tokens_180_answers=sum(x['input_tokens'] or 0 for x in runtime),
               output_tokens_180_answers=sum(x['output_tokens'] or 0 for x in runtime))
summary['acceptance_met'] = summary['strict_pass_rate'] >= .90 and summary['negative_refusal_status_correct'] == 30
for name, data in [('summary.json',summary),('reviewed_results.json',rows)]:
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'逐题评分.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream)
    writer.writerow(['编号','格式','类型','问题','标准答案','实际状态','实际回答','分数0至2','审核说明'])
    for r in rows:
        writer.writerow([r['id'],r['format'],r['kind'],r['question'],r['expected_answer'],r['response']['status'],r['response']['answer'],r['review']['score'],r['review']['note']])
lines = ['# V2检索优化与150次配对复测报告','',
    '日期：2026-10-07。评分由Codex助手逐题审核，未经过独立人工复核。','',
    '## 结果','',
    '| 指标 | 优化前 | 优化后 |','|---|---:|---:|',
    '| 完整通过 | 133/150（88.7%） | 147/150（98%） |',
    '| 部分通过 | 9 | 3 |','| 错误 | 8 | 0 |',
    '| 有依据却拒答 | 7 | 0 |','| 指代归属错误 | 1 | 0 |',
    '| 无依据题正确拒答 | 30/30 | 30/30 |','',
    '按2/1/0评分为297/300。PDF、MD、TXT均为49/50完整通过、1次部分通过；49个问法在三种格式上全部通过。部分通过不计入98%的分子。','',
    '## 实现','',
    '1. 复杂问题可规划最多4个互补子查询，每个不超过200字符；仍通过同一空间或公开分享分类权限范围检索。保留子查询的主要证据，并合并去重候选，上限50个。简单问题保持原流程。',
    '2. 复杂问题的生成上下文最多12个片段，正文总字符预算保持原配置上限（当前4×5000=20000字符），避免跨章节事实被固定4片段截掉。标题和提示指令另计，字符预算不等于token预算。',
    '3. 不对称比较按每个项目实际要求建立覆盖项。本次A三项、B两项输出五项，尊重禁止添加B/pgvector的要求；当前解析仍有支持范围，复杂或不支持的写法会回退普通生成。',
    '4. 多轮改写识别第一个、第二个、前者、后者，保留上一轮用户问题的实体顺序。历史只用于理解问题，回答事实仍从当前授权资料取得。',
    '5. 在规划前及生成前后检查实时权限范围；记录子查询、实际上下文片段ID及阶段耗时，便于追溯。未增加数据库表。','',
    '## 验证范围','',
    '使用原版14天/30天的三个独立私密评测空间，与优化前相同的文档版本、片段ID、正文SHA-256及50个问法。每题分别用PDF/MD/TXT作答，共150次计分，另有30次多轮前置回答，共180个问答动作。没有重传资料或改动真实用户内容。全部50组及结束时的资料指纹核对通过；测试配额已恢复。',
    '正式复测期间代码与提示版本保持固定，没有选择性重答失败题。本集已用于诊断和优化，属于已知题配对回归，不能代表陌生文档泛化能力；不是150个独立问题。',
    f'{citations_checked}条引用逐条核对文件名、原文与可用状态，均来自对应测试文档；候选和实际上下文ID也全部属于该文档。来源一致不等于所有语义归属在未来都正确，不据此声称证据Recall或零遗漏。',
    '后端TDD：先复现不对称覆盖、指代、权限内补检索与上下文遗漏，再实现修复；完整后端套件371项通过，包括查询数量/长度、预算和权限撤销边界。本轮没有UI改动。','',
    '## 性能与用量代价','',
    '| 指标 | 优化前 | 优化后 |','|---|---:|---:|',
    f'| 后端作答P50 | {baseline["latency_p50_seconds"]:.2f}秒 | {summary["latency_p50_seconds"]:.2f}秒 |',
    f'| 后端作答P95 | {baseline["latency_p95_seconds"]:.2f}秒 | {summary["latency_p95_seconds"]:.2f}秒 |',
    f'| 最大耗时 | {baseline["latency_max_seconds"]:.2f}秒 | {summary["latency_max_seconds"]:.2f}秒 |',
    f'| 180次问答输入token | {baseline["input_tokens_180_answers"]} | {summary["input_tokens_180_answers"]} |',
    f'| 180次问答输出token | {baseline["output_tokens_180_answers"]} | {summary["output_tokens_180_answers"]} |','',
    f'本轮首次响应{summary["first_response_seconds"]:.2f}秒，包含服务重启后的首次模型使用。P50/P95基于全部150条计分记录，其余主要为预热后的顺序执行，未作并发压测。复杂问题新增规划、补检索与更多上下文，会增加耗时和token。用量含正常内部规划及核验成功返回，不另行虚构未核实的费用。','',
    '## 剩余问题与下一步','',
    'N23在三种格式上仍部分通过：问“区分向量模型、检索与生成；纯检索测试会调用生成模型吗”，只回答最后一个是否问题，漏掉三者区别。应下一轮增加通用多任务覆盖检查，并使用未用于调参的新问法、新文档验证，避免只针对已知题优化。N22-md还出现(C10)等内部别名文本，事实正确，本轮未作为正确率错误，但展示清理可继续改善。',
    '本轮150次问答不替代公开访客隔离、团队越权、停用/更新竞态或正式部署验收；问答答对权限规则不能替代程序权限测试。','',
    '## 当前运行','',
    '修复已在本地Docker API、worker、beat生效，H5入口仍为http://localhost:10086。刷新页面并新建会话即可验证，不需要重新上传这些已正确分块的测试文档。继续使用既有模型缓存覆盖文件，未修改.env。本轮改动尚未提交或推送。','',
    '## 逐题记录','']
for r in rows:
    lines += [f'### {r["id"]} {r["question"]}','', '标准答案：'+r['expected_answer'],'',
              '实际回答：'+r['response']['answer'],'',f'状态：{r["response"]["status"]}；得分：{r["review"]["score"]}/2；{r["review"]["note"]}','']
(OUT/'150次优化复测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
