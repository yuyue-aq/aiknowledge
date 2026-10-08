"""Paired frozen-case comparison; retain regressions, raw grades and overrides."""
import csv,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/p1-rrf/500'
read=lambda path:json.loads(path.read_text(encoding='utf-8'))
old,new=(read(BASE/mode/'summary.json') for mode in ['dense','hybrid'])
d,h=({item['id']:item for item in read(BASE/mode/'reviewed_results.json')} for mode in ['dense','hybrid'])
assert len(d)==len(h)==500 and set(d)==set(h)
assert read(BASE/'dense/source-manifest.json')==read(BASE/'hybrid/source-manifest.json')
assert read(BASE/'dense/gold_cases.json')==read(BASE/'hybrid/gold_cases.json')
improved=[];regressed=[];strict_improved=[];strict_regressed=[]
for key,a in d.items():
    b=h[key]
    for field in ['question','expected_answer','format','required_facts']:
        assert a[field]==b[field]
    if b['review']['score']>a['review']['score']:improved.append(key)
    if b['review']['score']<a['review']['score']:regressed.append(key)
    if a['review']['score']<2 and b['review']['score']==2:strict_improved.append(key)
    if a['review']['score']==2 and b['review']['score']<2:strict_regressed.append(key)
summary={'dense':old,'hybrid':new,'same_cases_and_source_versions':True,
    'score_improved':improved,'score_regressed':regressed,'strict_improved':strict_improved,
    'strict_regressed':strict_regressed,'default_strategy':'dense',
    'decision':'Hybrid remains explicit: identifier ranking improves in small retrieval suite; complete answer pass rate is not higher.',
    'grade_method':'model-assisted; Dense T141 explicitly reviewed under frozen rubric; raw grades retained'}
(BASE/'paired-comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
with (BASE/'逐题配对对比.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['ID','问题','Dense评分','Hybrid评分','变化','Dense答案','Hybrid答案','Dense理由','Hybrid理由'])
    for key in sorted(d):
        a,b=d[key],h[key];delta=b['review']['score']-a['review']['score']
        writer.writerow([key,a['question'],a['review']['score'],b['review']['score'],delta,
            a['response']['answer'],b['response']['answer'],a['review']['reason'],b['review']['reason']])
lines=['# 阶段B固定500题配对对照','',
    '同一冻结500题、同一PDF/MD/TXT活动版本、同一模型和提示词；每题失败均保留。评分为独立模型辅助，未经过独立人工审核。','',
    '| 指标 | Dense | Hybrid |','|---|---:|---:|',
    f'| 完整通过 | {old["complete"]}/500 | {new["complete"]}/500 |',
    f'| 严格通过率 | {old["strict_pass_rate"]:.1%} | {new["strict_pass_rate"]:.1%} |',
    f'| 部分 / 错误 | {old["partial"]} / {old["incorrect"]} | {new["partial"]} / {new["incorrect"]} |',
    f'| 无依据题正确拒答 | {old["negative_refusal_status_correct"]}/50 | {new["negative_refusal_status_correct"]}/50 |',
    f'| 产品输入token | {old["input_tokens"]} | {new["input_tokens"]} |',
    f'| 产品输出token | {old["output_tokens"]} | {new["output_tokens"]} |',
    f'| P50 / P95秒 | {old["latency_p50_seconds"]:.2f} / {old["latency_p95_seconds"]:.2f} | {new["latency_p50_seconds"]:.2f} / {new["latency_p95_seconds"]:.2f} |','',
    '每路575次产品问答（含75次前置）；评分用量单独记录。两轮顺序执行、模型有随机性；Hybrid保留RRF顺序且未启用旧LLM子查询规划。这是整条策略链路对照，不是单独RRF公式的因果实验，也不是生产并发SLA。','',
    f'按2/1/0评分改善{len(improved)}题、退步{len(regressed)}题。转为完整通过{len(strict_improved)}题；从完整通过退步{len(strict_regressed)}题。','',
    '保留Dense默认。编号检索小样本收益不等于完整问答普遍收益；下一步应优先检查上下文选取、实体覆盖和排序，而非降低标准。','',
    'Dense原始模型完整通过487题；T141按既定规则复核为完整，最终488。原分与复核理由均保留；Hybrid没有评分覆盖。','',
    '## 转为完整通过','']
for key in strict_improved:lines.extend([f'- {key}：{d[key]["question"]}'])
lines.extend(['','## 从完整通过退步',''])
for key in strict_regressed:lines.extend([f'- {key}：{d[key]["question"]}；{h[key]["review"]["reason"]}'])
(BASE/'500题配对对照报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'strict_improved':strict_improved,'strict_regressed':strict_regressed,
    'score_improved':len(improved),'score_regressed':len(regressed),'source_versions_equal':True},ensure_ascii=False))
