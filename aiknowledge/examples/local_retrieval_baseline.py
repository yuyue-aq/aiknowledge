"""Real local BGE retrieval on the tuning split; no LLM or database.

Uses the official BGE Transformers CLS pooling recipe. The holdout split
is deliberately excluded. This is not production-adapter/E2E acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.retrieval import top_k_vectors
from app.services.token_budget import TokenBudget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import torch
    from transformers import AutoModel, AutoTokenizer
    started = perf_counter()
    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    cases = [case for case in dataset['cases'] if case['split'] == 'tune']
    paths = sorted((dataset_path.parent / 'sources').glob('*.txt'))
    names = [path.name for path in paths]
    documents = [path.read_text(encoding='utf-8').strip() for path in paths]
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    model = AutoModel.from_pretrained(args.model_path, local_files_only=True)
    model.eval()
    budget = TokenBudget(tokenizer, capacity=min(512, model.config.max_position_embeddings))
    prefix = '为这个句子生成表示以用于检索相关文章：'
    texts = documents + [prefix + case['question'] for case in cases]
    if any(budget.count(text) > budget.capacity for text in texts):
        raise ValueError('Fixture exceeds token capacity; never silently truncate evidence.')
    vectors = []
    with torch.inference_mode():
        for offset in range(0, len(texts), 8):
            inputs = tokenizer(texts[offset:offset+8], padding=True, truncation=False, return_tensors='pt')
            vectors.extend(torch.nn.functional.normalize(model(**inputs)[0][:, 0], p=2, dim=1).cpu().tolist())
    if any(len(vector) != 1024 for vector in vectors):
        raise ValueError('Expected 1024-dimensional BGE vectors.')
    rows = []
    for index, case in enumerate(cases):
        allowed = [doc for doc, name in enumerate(names) if case['scope'] == 'OWNER' or name[:2].isdigit()]
        expected = {ref['filename'] for ref in case['evidence_templates'] if ref.get('required', True)}
        ranked = top_k_vectors(vectors[len(documents)+index], [vectors[doc] for doc in allowed], 5)
        hits = [{'filename': names[allowed[doc]], 'score': score} for doc, score in ranked]
        actual = {hit['filename'] for hit in hits}
        rows.append({'case_id': case['id'], 'question': case['question'], 'scope': case['scope'], 'top_k': hits,
            'document_recall_at_5': len(actual & expected) / len(expected) if expected else None,
            'document_hit_at_5': bool(actual & expected) if expected else None,
            'answer_accuracy': None, 'refusal_correct': None})
    labelled = [row for row in rows if row['document_recall_at_5'] is not None]
    report = {'mode': 'real_local_transformers_retrieval_tuning_only', 'dataset_version': dataset['version'],
        'dataset_sha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest(), 'dimension': 1024,
        'top_k': 5, 'case_count': len(cases), 'labelled_case_count': len(labelled), 'holdout_evaluated': False,
        'document_recall_at_5': sum(row['document_recall_at_5'] for row in labelled) / len(labelled) if labelled else None,
        'document_hit_at_5': sum(row['document_hit_at_5'] for row in labelled) / len(labelled) if labelled else None,
        'answer_accuracy': None, 'elapsed_seconds': round(perf_counter()-started, 3), 'runs': rows,
        'limitations': '本地短 TXT 单片段；手写余弦与授权夹具过滤；无 PostgreSQL/FlagEmbedding/LLM，无法评定拒答或回答准确率。'}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('mode', 'case_count', 'labelled_case_count', 'holdout_evaluated', 'document_recall_at_5', 'document_hit_at_5', 'elapsed_seconds')}))


if __name__ == '__main__':
    main()
