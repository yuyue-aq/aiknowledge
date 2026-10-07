"""Handwritten Document -> Chunk -> Embedding -> cosine -> Top K.

Run `python examples/vector_search.py --demo` for known vectors, or
`python examples/vector_search.py --real --query "公开范围如何限制？"` for BGE.
Neither mode calls an LLM or uses LangChain/LlamaIndex.
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.retrieval import top_k_vectors

DOCUMENTS = [
    '访客只可检索分享链接允许且当前开放的分类，关闭分类后立即停止访问。',
    '上传的资料使用 tokenizer 分块，再编码为向量，保留原文位置。',
    '测试题标注标准答案与证据，冻结题集后可以重复运行并人工评分。',
]


async def main(args):
    if args.real:
        from app.core.config import Settings
        from app.infrastructure.embeddings.bge import BgeEmbeddingClient
        settings = Settings()
        model = BgeEmbeddingClient(model_name=settings.bge_model_name,
            expected_dimension=settings.bge_embedding_dimension, use_fp16=settings.bge_use_fp16)
        # These short examples also pass actual tokenizer limits before encode.
        documents = [part.content for text in DOCUMENTS for part in await model.split_document_text(text)]
        document_embeddings = await model.embed_documents(documents)
        query_embedding = (await model.embed_queries([args.query]))[0]
        print('模式：真实本地 BGE 编码（无 LLM）')
    else:
        documents = DOCUMENTS
        document_embeddings = [[1., 0., 0.], [.2, 1., 0.], [0., 0., 1.]]
        query_embedding = [1., 0., 0.]
        print('模式：确定性数学示例，使用已知向量；不代表真实语义检索效果')
    for rank, (index, score) in enumerate(top_k_vectors(query_embedding, document_embeddings, args.top_k), 1):
        print(f'{rank}. score={score:.6f} | {documents[index]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--real', action='store_true')
    parser.add_argument('--query', default='公开范围如何限制？')
    parser.add_argument('--top-k', type=int, default=3)
    asyncio.run(main(parser.parse_args()))
