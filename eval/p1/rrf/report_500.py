"""Validate artifacts and publish honest model-assisted evaluation statistics."""
import csv
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID
ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/p1-rrf/500'
OUT=BASE/sys.argv[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
rows=read(OUT/'results.json')
grades={x['id']:x for x in read(OUT/'model-grades.json')}
overrides=read(OUT/'review-overrides.json') if (OUT/'review-overrides.json').exists() else {}
ids=[]
for r in rows:
    for key in ['response','setup_response']:
        if r.get(key) and r[key].get('message_id'):ids.append(str(UUID(r[key]['message_id'])))
sql="SELECT json_agg(t) FROM (SELECT message_id, rewritten_question, total_latency_ms AS latency_ms, input_tokens, output_tokens, prompt_version, model_snapshot AS model, retrieval_config_snapshot AS retrieval_config, retrieved_chunk_ids FROM rag_runs WHERE message_id IN ("+','.join("'"+i+"'" for i in ids)+") ORDER BY created_at) t;"
proc=subprocess.run([os.environ.get('AIKNOWLEDGE_EVAL_DOCKER','docker'),'exec','-i','aiknowledge-postgres-1','psql','-U','aiknowledge','-d','aiknowledge_p1','-t','-A'],input=sql,text=True,encoding='utf-8',capture_output=True,check=True)
runtime=json.loads(proc.stdout)
assert len(runtime)==len(ids)
save(OUT/'run-metadata.json',runtime)
by_message={x['message_id']:x for x in runtime}
assert len(rows)==500 and len(grades)==500
assert read(OUT/'source-integrity-check.json')['status']=='PASSED'
checked=0
for r in rows:
    doc=read(OUT/f'document-{r["format"]}.json')
    by_ordinal={c['ordinal']:c['content'] for c in doc['chunks']}
    chunk_ids={c['chunk_id'] for c in doc['chunks']}
    if r['response'].get('message_id'):
        meta=by_message[r['response']['message_id']]
        assert set(meta['retrieved_chunk_ids'])<=chunk_ids
        assert set(meta['model']['context_chunk_ids'])<=chunk_ids
        r['runtime']=meta
    for c in r['response'].get('citations',[]):
        assert c.get('source_available',True)
        assert c['document_name']==doc['document']['original_filename']
        assert c['quoted_text']==by_ordinal[c['ordinal']]
        checked+=1
    g=overrides.get(r['id'],grades[r['id']])
    r['review']={'score':g['score'],'reason':g['reason'],'method':'assistant override' if r['id'] in overrides else 'model-assisted'}
    if r['response']['status'] in ['FAILED','HTTP_ERROR']:assert g['score']==0
def stats(items):
    c=Counter(r['review']['score'] for r in items)
    return {'total':len(items),'complete':c[2],'partial':c[1],'incorrect':c[0],'strict_pass_rate':c[2]/len(items)}
s=stats(rows)
s.update(by_kind={k:stats([r for r in rows if r['kind']==k]) for k in sorted({r['kind'] for r in rows})},
         by_format={f:stats([r for r in rows if r['format']==f]) for f in ['pdf','md','txt']},
         negative_refusal_status_correct=sum(not r['answerable'] and r['response']['status']=='INSUFFICIENT_EVIDENCE' for r in rows),
         citation_source_checks=checked,source_integrity='PASSED',
         input_tokens=sum(x['input_tokens'] or 0 for x in runtime),output_tokens=sum(x['output_tokens'] or 0 for x in runtime),
         product_actions=len(runtime),prompt_versions=sorted({x['prompt_version'] for x in runtime}),
         grader_usage=read(OUT/'judge-usage.json'),assistant_overrides=len(overrides))
lat=sorted(r['runtime']['latency_ms']/1000 for r in rows if r.get('runtime'))
s.update(latency_p50_seconds=statistics.median(lat),latency_p95_seconds=lat[math.ceil(.95*len(lat))-1],latency_max_seconds=max(lat))
s['target_met']=s['complete']>=451
save(OUT/'summary.json',s);save(OUT/'reviewed_results.json',rows)
with (OUT/'逐题评分.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['编号','题型','格式','前置问题','问题','标答','状态','实际回答','得分','评分原因','方法'])
    for r in rows:w.writerow([r['id'],r['kind'],r['format'],r.get('setup_question',''),r['question'],r['expected_answer'],r['response']['status'],r['response']['answer'],r['review']['score'],r['review']['reason'],r['review']['method']])
lines=['# V2 500题回归评测报告','',f'日期：2026-10-08；轮次：{OUT.name}。','',
       f'完整通过{s["complete"]}/500（{s["strict_pass_rate"]:.1%}），部分通过{s["partial"]}，错误{s["incorrect"]}。目标高于90%，至少451题完整通过，本轮'+('达标。' if s['target_met'] else '未达标。'),'',
       '## 题库与规则','',
       '固定500个不同问题，81事实、194综合、100计算、75多轮追问、50拒答；按题分配PDF167、MD167、TXT166。多轮额外75次前置问答，不计入500题分数。原版虚构档案统一14天/30天，使用三个独立私密测试空间，结束恢复测试前套餐。','',
       '题库、必答事实和标准在运行前固定，SHA-256见dataset-manifest.json。组合题和假设计算共享事实且相关，不是500份独立资料，也不声称500个独立语义事实。拒答题索取未记录值，不允许猜测。只有完整2分计入通过率，1分不计；服务失败保留计0分。','',
       '评分采用独立DeepSeek Flash调用辅助，检查全部必答事实；评分结果保留原始理由；如有助手复核修正，单独记录到review-overrides.json并统计数量。评分模型与作答模型同源，可能存在相关偏差，结果未经过独立人工审核。不是正式上线保证。','',
       '## 结果分类','', '| 题型 | 完整通过 | 部分通过 | 错误 |','|---|---:|---:|---:|']
for k,v in s['by_kind'].items():lines.append(f'| {k} | {v["complete"]}/{v["total"]} | {v["partial"]} | {v["incorrect"]} |')
lines+=['',f'50道无依据题中{s["negative_refusal_status_correct"]}道状态为INSUFFICIENT_EVIDENCE。{checked}条引用逐条匹配当前原文、文件名和可用状态；所有候选与实际上下文片段ID属于对应测试文档。引用来源一致不等同于完整语义正确。资料指纹开始、逐题及结束均校验一致。','',
        '## 性能与用量','',f'本轮最多三空间并行，各空间串行，不是正式并发压测。后端P50 {s["latency_p50_seconds"]:.2f}秒，P95 {s["latency_p95_seconds"]:.2f}秒，最大{s["latency_max_seconds"]:.2f}秒。不同于上一轮顺序执行，不能直接当作同负载性能提升/下降。',
        f'产品问答{s["product_actions"]}次（含前置）：输入token {s["input_tokens"]}，输出token {s["output_tokens"]}；独立评分用量见judge-usage.json，不混入产品问答用量。','',
        '## 低分明细','']
for r in rows:
    if r['review']['score']<2:
        lines += [f'### {r["id"]}（{r["review"]["score"]}/2）','',r['question'],'','标准：'+r['expected_answer'],'','实际：'+r['response']['answer'],'','原因：'+r['review']['reason'],'']
(OUT/'500题评测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(s,ensure_ascii=False,indent=2))
