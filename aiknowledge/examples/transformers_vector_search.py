"""Offline BGE sanity check using the official CLS pooling recipe.

This standalone example uses the existing Transformers/PyTorch runtime.
It does not validate the production FlagEmbedding adapter or PostgreSQL.
Source: https://huggingface.co/BAAI/bge-large-zh-v1.5#using-huggingface-transformers
"""
import argparse
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
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import torch
    from transformers import AutoModel, AutoTokenizer
    started = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    model = AutoModel.from_pretrained(args.model_path, local_files_only=True)
    model.eval()
    budget = TokenBudget(tokenizer, capacity=min(512, model.config.max_position_embeddings))
    documents = [
        '访客只可检索分享链接允许且当前开放的分类，关闭分类后立即停止访问。',
        '上传的资料使用 tokenizer 分块，再编码为向量，保留原文位置。',
        '测试题标注标准答案与证据，冻结题集后可以重复运行并人工评分。',
    ]
    questions = ['公开范围如何限制？', '上传资料为什么要分块？', '如何重复测试回答质量？']
    texts = documents + ['为这个句子生成表示以用于检索相关文章：'+question for question in questions]
    assert all(budget.count(text) <= budget.capacity for text in texts)
    with torch.inference_mode():
        inputs = tokenizer(texts, padding=True, truncation=False, return_tensors='pt')
        vectors = torch.nn.functional.normalize(model(**inputs)[0][:, 0], p=2, dim=1).cpu().tolist()
    assert all(len(vector) == 1024 for vector in vectors)
    runs = [{'question': question, 'expected_top_document': index,
        'top_k': [{'document_index': doc_index, 'score': score, 'text': documents[doc_index]}
            for doc_index, score in top_k_vectors(vectors[len(documents)+index], vectors[:len(documents)], 3)]}
        for index, question in enumerate(questions)]
    report = {'mode': 'real_local_bge_transformers_sanity', 'dimension': 1024,
        'model_path': str(Path(args.model_path).resolve()), 'elapsed_seconds': round(perf_counter()-started, 3),
        'top1_correct': sum(item['top_k'][0]['document_index'] == item['expected_top_document'] for item in runs),
        'total': len(runs), 'runs': runs,
        'limitations': '3题本地编码冒烟检查；无LLM、无数据库，不是50题质量基线或生产适配器验收。'}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ['mode', 'dimension', 'elapsed_seconds', 'top1_correct', 'total']}))


if __name__ == '__main__':
    main()
