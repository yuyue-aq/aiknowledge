import math
from uuid import UUID

import pytest

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError
from app.services.bm25 import Bm25Retriever, analyze


def chunk(n, text):
    return RetrievedChunk(UUID(int=n), UUID(int=100+n), '合成.txt', text, None, n, 0.)


def test_standard_score_and_repeated_query_words():
    corpus=[chunk(1,'alpha alpha beta'),chunk(2,'beta')]
    hits=Bm25Retriever().rank('alpha',corpus,5)
    assert [x.id for x in hits]==[UUID(int=1)]
    assert hits[0].score==pytest.approx(math.log(2)*4.4/3.65)
    assert Bm25Retriever().rank('alpha alpha',corpus,5)==hits


def test_chinese_identifiers_and_versions_remain_distinct():
    assert analyze('PRJ-A v2.0.1 SCOPE_CHANGED')==['prj-a','v2.0.1','scope_changed']
    corpus=[chunk(1,'PRJ-A v2.0.1 检索范围变化'),chunk(2,'PRJ-B v2.0.2 库存规则')]
    assert [x.id for x in Bm25Retriever().rank('PRJ-A',corpus,5)]==[UUID(int=1)]
    assert [x.id for x in Bm25Retriever().rank('范围变化',corpus,5)]==[UUID(int=1)]
    assert Bm25Retriever().rank('v2.0.9',corpus,5)==()


def test_deterministic_ties_empty_and_no_match():
    a,b=chunk(1,'同一规则'),chunk(2,'同一规则')
    assert [x.id for x in Bm25Retriever().rank('规则',[b,a],20)]==[a.id,b.id]
    assert Bm25Retriever().rank('x',[],5)==()
    assert Bm25Retriever().rank('未出现的代码_999',[a],5)==()
    assert Bm25Retriever().rank('!!!',[a],5)==()


def test_limit_rejects_incomplete_corpus_instead_of_silently_scoring_prefix():
    with pytest.raises(RetrievalError) as error:
        Bm25Retriever(max_corpus_chunks=1).rank('规则',[chunk(1,'规则'),chunk(2,'规则')],5)
    assert error.value.code=='BM25_CORPUS_LIMIT'


@pytest.mark.parametrize('k',[0,21,True])
def test_invalid_k(k):
    with pytest.raises(RetrievalError):Bm25Retriever().rank('规则',[chunk(1,'规则')],k)
