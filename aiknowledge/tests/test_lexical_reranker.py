from app.domain.rag import RankedSourceChunk, SourceChunk
from app.services.lexical_reranker import LexicalDenseReranker


def test_keyword_reranking_preserves_scoped_candidates_and_original_scores():
    items = [RankedSourceChunk(SourceChunk('a', '说明', '系统支持上传文件'), .9),
             RankedSourceChunk(SourceChunk('b', '说明', '项目开发时间为七月至九月'), .5)]
    result = LexicalDenseReranker().rerank('项目开发时间', items)
    assert result[0] is items[1]
    assert {item.source.id for item in result} == {'a', 'b'}
    assert [item.score for item in result] == [.5, .9]


def test_empty_or_no_keyword_overlap_keeps_dense_order():
    reranker = LexicalDenseReranker()
    assert reranker.rerank('test', []) == ()
    items = [RankedSourceChunk(SourceChunk('a', '说明', '库存'), .9),
             RankedSourceChunk(SourceChunk('b', '说明', '档案'), .5)]
    assert reranker.rerank('xyz', items) == tuple(items)
