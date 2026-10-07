"""Publish paired rounds only after the final full round exceeds 90%."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'output/evaluation/20261007-large500'
FINAL=sys.argv[1] if len(sys.argv)>1 else 'round-3'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
old=read(BASE/'round-2/summary.json')
new=read(BASE/FINAL/'summary.json')
assert new['total']==500 and new['target_met']
original=read(BASE/'round-2/reviewed_results.json')
latest=read(BASE/FINAL/'reviewed_results.json')
by_old={r['id']:r for r in original}
assert len(latest)==500 and {r['id'] for r in latest}==set(by_old)
for r in latest:
    assert all(r.get(k)==by_old[r['id']].get(k) for k in ['question','expected_answer','required_facts','setup_question','kind','format','answerable'])
assert read(BASE/'round-2/source-manifest.json')==read(BASE/FINAL/'source-manifest.json')
fixed=[r['id'] for r in latest if r['review']['score']==2 and by_old[r['id']]['review']['score']<2]
regressed=[r['id'] for r in latest if r['review']['score']<2 and by_old[r['id']]['review']['score']==2]
remaining=[r['id'] for r in latest if r['review']['score']<2]
delta={'fixed_to_complete':fixed,'regressed_from_complete':regressed,'remaining_noncomplete':remaining}
(BASE/'paired-comparison.json').write_text(json.dumps(delta,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# V2 500题测试与优化结果','',
       '日期：2026-10-07（Asia/Shanghai）。结果采用模型辅助评分及助手复核，未经过独立人工评分。','',
       f'最终完整通过 **{new["complete"]}/500（{new["strict_pass_rate"]:.1%}）**，达到高于90%的目标（至少451/500）。部分通过不计入分子。','',
       '## 轮次记录','',
       '| 轮次 | 完整通过 | 部分通过 | 错误 | 结论 |','|---|---:|---:|---:|---|',
       '| 首次并行尝试 | 114条已运行，15条正常作答 | — | 99条服务失败 | 中止修复，全部原始记录保留，不冒充完整500题结果 |',
       f'| 排队修复后 round-2 | {old["complete"]}/500（{old["strict_pass_rate"]:.1%}） | {old["partial"]} | {old["incorrect"]} | 未达标 |',
       f'| 多要求修复后 {FINAL} | {new["complete"]}/500（{new["strict_pass_rate"]:.1%}） | {new["partial"]} | {new["incorrect"]} | 达标 |','',
       f'与round-2逐题配对：{len(fixed)}条原低分变为完整通过，{len(regressed)}条原通过题本轮失分。没有只重测失败题或隐去退步题；运行受模型随机性影响，本次修复并不保证每道题始终相同。详情见paired-comparison.json。','',
       '## 固定数据与评分','',
       '500个不同问题：81事实、194综合、100计算、75多轮追问、50拒答。每题只分配一个格式，共PDF167、MD167、TXT166；多轮另有75次前置回答。综合题由81条事实组成不同组合，计算题有明确的假设数值变化；不是500份独立文档或500个独立语义事实。三个格式题目不同且复杂度分布不同，不据此比较格式优劣。',
       '原版虚构资料保持14天/30天，三个独立私密空间，不覆盖用户原资料。两轮500题的题目、标准、必答事实、文档版本、片段ID及正文指纹相同，逐题和结束校验均通过。每轮期间容器实现保持固定，变更后从头全量运行。固定题库SHA-256见dataset-manifest.json。',
       '评分2=完整正确且遵循范围，1=核心正确但遗漏或范围不符，0=主要事实错误/归属错误/编造/不当拒答或服务失败；仅2分计完整通过。使用独立DeepSeek Flash调用辅助评分，助手复核低分、计算/拒答和通过题抽样；评分与作答模型同源，可能存在相关偏差。最终成绩属于已知资料回归，不是陌生资料盲测。','',
       '## 修复','',
       '1. 本地向量模型同时收到正常请求时改为有限时间排队，而不是立即报模型不可用；保留超时底层线程未结束时禁止重复推理的保护。',
       '2. 识别1）/1./1、等编号多任务、逐项要求、正反职责要求，触发同权限范围的子查询及上下文覆盖。没有将题库答案或虚构人物事实写入产品代码。',
       '3. 保留“排在第二位、排在后面、最后介绍、接着上一问”的用户上下文；明确用户介绍顺序与资料真实排名的区别。历史回答仍不作为事实证据。',
       '4. 允许结合原文基准值与用户明确假设进行计算，并说明推算来源；未记录的真实值仍不得猜测。',
       '后端TDD先复现并发拒绝、编号任务识别和指代错误，再修复；最终381项后端测试通过。未改UI、.env或真实用户资料。','',
       '## 最终分项结果','', '| 题型 | 完整通过 | 部分通过 | 错误 |','|---|---:|---:|---:|']
for kind,s in new['by_kind'].items():lines.append(f'| {kind} | {s["complete"]}/{s["total"]} | {s["partial"]} | {s["incorrect"]} |')
lines += ['',f'50道无依据题中{new["negative_refusal_status_correct"]}道状态正确；最终{new["citation_source_checks"]}条引用逐条匹配原文、文档名和可用状态。候选及实际上下文均属对应测试文档。来源一致不能替代语义正确或证据Recall评测。','',
          '## 耗时与用量','', '| 指标 | round-2 | 最终 |','|---|---:|---:|']
for key,label in [('latency_p50_seconds','P50秒'),('latency_p95_seconds','P95秒'),('latency_max_seconds','最大秒'),('input_tokens','575次产品问答输入token'),('output_tokens','575次产品问答输出token')]:
    a,b=old[key],new[key]
    lines.append(f'| {label} | {a:.2f} | {b:.2f} |' if 'seconds' in key else f'| {label} | {a} | {b} |')
lines += ['', '每轮最多三个空间并行，各空间串行，含重启后首次模型使用；不当作正式生产并发压测。补检索会增加耗时和token，独立评分用量见各轮judge-usage.json，未混入产品问答用量。','',
          '## 剩余问题','',f'最终仍有{len(remaining)}条未完整通过，不承诺零遗漏。详情见最终500题评测报告.md与逐题评分.csv。后续优先使用未参与调参的新资料、新问法验证，并继续改善子查询证据选择与多要求覆盖。',
          '这轮不替代公开访客隔离、团队越权、资料停用/更新竞态或正式部署验收。题目答对权限规则，不等于实际权限门禁已验收。','',
          '## 如何查看','',
          '- 500题测试数据.csv：题目、前置问题、必答事实、标准答案。',
          f'- {FINAL}/逐题评分.csv：实际回答与评分理由。',
          f'- {FINAL}/500题评测报告.md：完整分类结果与低分明细。',
          '- round-1/results.json：原始中止轮次，99条服务失败保留。',
          '- round-2/：未达标的完整500题记录。','',
          '修复已在本地Docker生效。访问http://localhost:10086，刷新并新建会话即可验证，无需重传这些测试文档。三个评测空间配额已恢复初始FREE。代码与评测产物尚未提交或推送。']
(BASE/'500题测试与优化总报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'final':new['complete'],'rate':new['strict_pass_rate'],'fixed':len(fixed),'regressed':len(regressed),'remaining':len(remaining)},ensure_ascii=False))
