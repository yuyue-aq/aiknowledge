"""Compare all paired scores honestly; never alter answers or grading."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/p1-reranker/500/hybrid_rerank'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    current=read(OUT/'reviewed_results.json')
    assert len(current)==500
    result={'notes':'同一固定500题与活动资料版本；模型辅助评分，同源偏差仍存在。未作为生产性能或普遍准确率保证。',
            'new_summary':read(OUT/'summary.json'),'comparisons':{}}
    for mode in ['dense','hybrid']:
        baseline=ROOT/'output/p1-rrf/500'/mode
        before={x['id']:x for x in read(baseline/'reviewed_results.json')}
        assert set(before)=={x['id'] for x in current}
        assert read(baseline/'source-manifest.json')==read(OUT/'source-manifest.json')
        changes=[]
        for after in current:
            old=before[after['id']]
            for key in ['question','expected_answer','format','answerable','setup_question']:
                assert old.get(key)==after.get(key),(after['id'],key)
            a,b=old['review']['score'],after['review']['score']
            if a!=b:
                changes.append({'id':after['id'],'before':a,'after':b,
                                'before_reason':old['review']['reason'],'after_reason':after['review']['reason']})
        result['comparisons'][mode]={'baseline_summary':read(baseline/'summary.json'),
            'became_complete':[x['id'] for x in changes if x['before']<2 and x['after']==2],
            'lost_complete':[x['id'] for x in changes if x['before']==2 and x['after']<2],
            'score_changes':changes}
    (OUT/'paired-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({m:{k:v for k,v in d.items() if k in ['became_complete','lost_complete']} for m,d in result['comparisons'].items()},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
