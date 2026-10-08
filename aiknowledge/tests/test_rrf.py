from dataclasses import replace
from uuid import UUID

import pytest

from app.domain.conversations import RetrievedChunk
from app.services.hybrid_retrieval import reciprocal_rank_fusion


def chunk(number, score=0.5):
    return RetrievedChunk(UUID(int=number), UUID(int=100), 'fixture.txt', str(number), None, number, score)


def test_rrf_uses_rank_not_incompatible_scores_and_preserves_provenance():
    a, b, c = chunk(1), chunk(2), chunk(3)
    result = reciprocal_rank_fusion([a, b], [replace(b, score=100), replace(c, score=90)], top_k=3)
    assert [x.id for x in result] == [b.id, a.id, c.id]
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert result[0].dense_rank == 2 and result[0].bm25_rank == 1
    assert result[0].dense_score == .5 and result[0].bm25_score == 100
    assert result[0].fusion_rank == 1 and result[0].score_kind == 'rrf'
    assert result[1].bm25_rank is None


def test_rrf_deduplicates_within_each_branch_and_uses_stable_id_ties():
    a, b = chunk(1), chunk(2)
    result = reciprocal_rank_fusion([b, b, a], [a, b, b], top_k=5)
    assert [x.id for x in result] == [a.id, b.id]
    assert all(x.score == pytest.approx(1/61+1/62) for x in result)


def test_rrf_keeps_keyword_only_evidence_and_empty_branches():
    a=chunk(1)
    assert reciprocal_rank_fusion([], [], top_k=3) == ()
    result=reciprocal_rank_fusion([], [a], top_k=3)
    assert result[0].id==a.id and result[0].dense_rank is None
    assert result[0].score==pytest.approx(1/61)


@pytest.mark.parametrize('constant,k', [(0,3),(True,3),(60,0),(60,True)])
def test_rrf_rejects_invalid_parameters(constant,k):
    with pytest.raises(ValueError):reciprocal_rank_fusion([], [], top_k=k, rank_constant=constant)
