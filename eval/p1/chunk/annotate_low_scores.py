"""Explicit D literal annotations and separately recorded rubric review."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-chunk/500/dense'
TARGETS={
    'T083':['BAAI/bge-large-zh-v1.5'],
    'T089':['PDF、Markdown和TXT'],
    'T104':['Redis用于热点库存查询缓存'],
    'T200':['当前所在地：南京'],
    'T209':['系统使用余弦相似度衡量相关性'],
    'T420':['分享范围内已授权且已启用'],
    'T439':['160秒','60秒'],
    'T428':['TXT先按空行'],
}


def normalize(text):
    return re.sub(r'\s+','',text)


def main():
    evidence=json.loads((OUT/'low-score-evidence.json').read_text(encoding='utf-8'))
    overrides=json.loads((OUT/'review-overrides.json').read_text(encoding='utf-8-sig')) if (OUT/'review-overrides.json').exists() else {}
    annotations=[]
    for row in evidence:
        if row['id'] in overrides and overrides[row['id']]['score']==2:
            annotations.append({'id':row['id'],'classification':'rubric_review_complete','reason':overrides[row['id']]['reason']})
            continue
        if row['id'] not in TARGETS:
            annotations.append({'id':row['id'],'classification':'unannotated_requires_review'})
            continue
        facts=[]
        for target in TARGETS[row['id']]:
            ids={x['chunk_id'] for x in row['all_document_chunks'] if normalize(target) in normalize(x['content'])}
            assert ids,(row['id'],target)
            facts.append({'literal':target,'evidence_ids':sorted(ids),
                'in_saved_candidates':bool(ids & {x['chunk_id'] for x in row['candidate_chunks']}),
                'in_context':bool(ids & {x['chunk_id'] for x in row['context_chunks']})})
        classification='generation_or_reference_failure_with_context' if all(x['in_context'] for x in facts) else 'target_evidence_not_selected_in_context'
        annotations.append({'id':row['id'],'facts':facts,'classification':classification,
                            'notes':'仅对缺失事实作明确词句定位，不改变原始答案、标准或分数。'})
    (OUT/'failure-annotations.json').write_text(json.dumps(annotations,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(annotations,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
