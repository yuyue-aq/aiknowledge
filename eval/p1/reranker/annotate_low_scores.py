"""Explicit literal annotations for the six observed failures; no grading override."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-reranker/500/hybrid_rerank'
TARGETS={
    'T176':['2026年7月至2026年9月'],
    'T191':['2026-10-03'],
    'T212':['重复请求、库存不足、事务回滚与并发出库的后端测试'],
    'T245':['江宁信息学院'],
    'T420':['分享范围内已授权且已启用'],
    'T439':['160秒','60秒'],
}


def normalize(text):
    return re.sub(r'\s+','',text)


def main():
    evidence=json.loads((OUT/'low-score-evidence.json').read_text(encoding='utf-8'))
    annotations=[]
    for row in evidence:
        if row['id'] not in TARGETS:
            annotations.append({'id':row['id'],'classification':'unannotated_requires_review'})
            continue
        facts=[]
        for target in TARGETS[row['id']]:
            ids={x['chunk_id'] for x in row['all_document_chunks'] if normalize(target) in normalize(x['content'])}
            assert ids,(row['id'],target)
            facts.append({'literal':target,'evidence_ids':sorted(ids),
                'in_original_rrf_pool':bool(ids & {x['chunk_id'] for x in row['before_pool']}),
                'in_final_candidates':bool(ids & {x['chunk_id'] for x in row['candidate_chunks']}),
                'in_context':bool(ids & {x['chunk_id'] for x in row['context_chunks']})})
        classification='generation_or_reference_failure_with_context' if all(x['in_context'] for x in facts) else 'target_evidence_not_selected_in_context'
        annotations.append({'id':row['id'],'facts':facts,'classification':classification,
                            'notes':'仅对缺失事实作明确词句定位，不改变原始答案、标准或分数。'})
    (OUT/'failure-annotations.json').write_text(json.dumps(annotations,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(annotations,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
