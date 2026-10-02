from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from app.domain.conversations import EvalCase, EvalScope, RetrievedChunk
from app.domain.evaluation import EvidenceRef
from app.domain.rag import AnswerStatus
from app.services.evaluation_metrics import retrieval_metrics, refusal_correct


def case():
    return EvalCase(uuid4(), uuid4(), '问题', '答案', (), EvalScope.OWNER, (), datetime.now(UTC))


def chunk(document_id=None):
    return RetrievedChunk(uuid4(), document_id or uuid4(), '资料', 'abcdefghij', 1, 1, .9,
        document_version_id=uuid4(), source_block_id='block-1', char_start=0, char_end=10)


def test_document_metrics_use_actual_retrieved_documents_not_citation_count():
    first, second = chunk(), chunk()
    question = replace(case(), answerable=True, expected_document_ids=(first.document_id, second.document_id))
    metrics = retrieval_metrics(question, [first, replace(first, id=uuid4())], k=4)
    assert metrics['document_recall_at_k'] == .5
    assert metrics['document_hit_at_k'] == 1.
    assert metrics['retrieved_count'] == 2
    assert retrieval_metrics(question, [], k=4)['document_hit_at_k'] == 0.
    assert retrieval_metrics(case(), [first], k=4)['document_recall_at_k'] is None


def test_evidence_overlap_and_full_cover_are_separate_and_hash_checked():
    hit = chunk()
    ref = EvidenceRef(hit.document_id, hit.document_version_id, 'block-1', 2, 7, sha256(b'cdefg').hexdigest())
    question = replace(case(), answerable=True, evidence_refs=(ref,))
    manifest = {hit.document_version_id}
    full = retrieval_metrics(question, [hit], k=4, available_versions=manifest)
    assert full['evidence_recall_at_k'] == 1.
    partial_hit = replace(hit, content='abcd', char_end=4)
    partial = retrieval_metrics(question, [partial_hit], k=4, available_versions=manifest)
    assert partial['evidence_recall_at_k'] == 0.
    assert partial['evidence_overlap_at_k'] == 1.
    wrong = replace(hit, content='xxxxxxxxxx')
    assert retrieval_metrics(question, [wrong], k=4, available_versions=manifest)['evidence_recall_at_k'] == 0.
    assert retrieval_metrics(question, [hit], k=4, available_versions=set())['evidence_recall_at_k'] is None
    assert retrieval_metrics(question, [hit], k=4)['evidence_recall_at_k'] is None


def test_evidence_can_be_fully_covered_by_adjacent_chunks():
    hit = chunk()
    ref = EvidenceRef(hit.document_id, hit.document_version_id, 'block-1', 2, 7, sha256(b'cdefg').hexdigest())
    question = replace(case(), answerable=True, evidence_refs=(ref,))
    left, right = replace(hit, content='abcde', char_end=5), replace(hit, id=uuid4(), content='fghij', char_start=5)
    assert retrieval_metrics(question, [left, right], k=4, available_versions={hit.document_version_id})['evidence_recall_at_k'] == 1.


@pytest.mark.parametrize('start,end,hash_value', [(-1, 3, 'a'*64), (4, 4, 'a'*64), (5, 3, 'a'*64), (0, 1, 'invalid')])
def test_invalid_evidence_coordinates_and_hash_are_rejected(start, end, hash_value):
    with pytest.raises(ValueError):
        EvidenceRef(uuid4(), uuid4(), 'block-1', start, end, hash_value)


def test_model_failure_is_never_a_correct_refusal():
    question = replace(case(), answerable=False, expected_behavior='INSUFFICIENT_EVIDENCE')
    assert refusal_correct(question, AnswerStatus.FAILED) is False
    assert refusal_correct(question, AnswerStatus.INSUFFICIENT_EVIDENCE) is True
    assert refusal_correct(question, AnswerStatus.OUT_OF_SCOPE) is False
    assert refusal_correct(case(), AnswerStatus.INSUFFICIENT_EVIDENCE) is None
