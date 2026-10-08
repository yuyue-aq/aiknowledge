"""Save evidence layers for honest human review of all noncomplete answers."""
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-reranker/500/hybrid_rerank'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    grades={x['id']:x for x in read(OUT/'model-grades.json') if x['score']<2}
    rows=[x for x in read(OUT/'results.json') if x['id'] in grades]
    ids=[str(UUID(x['response']['message_id'])) for x in rows if x['response'].get('message_id')]
    metadata={}
    if ids:
        sql="SELECT json_agg(t) FROM (SELECT message_id,model_snapshot,retrieval_config_snapshot,retrieved_chunk_ids FROM rag_runs WHERE message_id IN ("+','.join("'"+x+"'" for x in ids)+")) t;"
        proc=subprocess.run([os.environ.get('AIKNOWLEDGE_EVAL_DOCKER','docker'),'exec','-i','aiknowledge-postgres-1','psql','-U','aiknowledge','-d','aiknowledge_p1','-t','-A'],input=sql,text=True,encoding='utf-8',capture_output=True,check=True)
        metadata={x['message_id']:x for x in json.loads(proc.stdout)}
    evidence=[]
    for row in rows:
        meta=metadata.get(row['response'].get('message_id'),{})
        doc=read(OUT/f"document-{row['format']}.json")
        chunks={x['chunk_id']:x for x in doc['chunks']}
        config=meta.get('retrieval_config_snapshot',{})
        context=meta.get('model_snapshot',{}).get('context_chunk_ids',[])
        def content(cid):
            item=chunks[cid]
            return {'chunk_id':cid,'ordinal':item['ordinal'],'content':item['content']}
        evidence.append({'id':row['id'],'question':row['question'],'expected':row['expected_answer'],
            'answer':row['response']['answer'],'raw_grade':grades[row['id']],
            'candidate_chunks':[content(x) for x in meta.get('retrieved_chunk_ids',[])],
            'context_chunks':[content(x) for x in context],
            'before_pool':config.get('branches',{}).get('fusion',[]),
            'scored_candidates':meta.get('model_snapshot',{}).get('retrieved_chunks',[]),
            'all_document_chunks':[content(x) for x in chunks],
            'review_note':'层次证据供复核；仅存在于文档/候选不等于已进入上下文。未覆盖模型原始评分。'})
    (OUT/'low-score-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'id':x['id'],'context_ordinals':[c['ordinal'] for c in x['context_chunks']],
                      'candidate_ordinals':[c['ordinal'] for c in x['candidate_chunks']]} for x in evidence],ensure_ascii=False))


if __name__=='__main__':
    main()
