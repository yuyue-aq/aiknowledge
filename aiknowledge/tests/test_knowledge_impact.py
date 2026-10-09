from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from app.domain.conversations import EvalCase, EvalScope
from app.domain.evaluation import EvidenceRef
from app.services.knowledge_impact import build_knowledge_impact


def _case(*, version_id, document_id, question='这个规则是什么？', behavior='ANSWERED'):
    ref = EvidenceRef(
        document_id=document_id,
        document_version_id=version_id,
        source_block_id='paragraph-1',
        char_start=0,
        char_end=2,
        text_hash=sha256('依据'.encode()).hexdigest(),
    )
    return EvalCase(
        id=uuid4(), space_id=uuid4(), question=question, expected_answer='依据',
        expected_document_ids=(document_id,), scope=EvalScope.OWNER, category_ids=(),
        created_at=datetime(2026, 10, 9, tzinfo=UTC), answerable=True,
        expected_behavior=behavior, evidence_refs=(ref,),
    )


def test_knowledge_impact_marks_only_evidence_from_old_or_unavailable_versions():
    current_doc, updated_doc, deleted_doc = uuid4(), uuid4(), uuid4()
    current_version, old_version, deleted_version = uuid4(), uuid4(), uuid4()
    cases = [
        _case(version_id=current_version, document_id=current_doc, question='当前规则是什么？'),
        _case(version_id=old_version, document_id=updated_doc, question='更新后的规则是什么？'),
        _case(version_id=deleted_version, document_id=deleted_doc, question='已删除资料里的规则是什么？'),
    ]

    report = build_knowledge_impact(
        documents=[
            {'id': current_doc, 'name': 'current.md', 'active_version_id': current_version, 'available': True},
            {'id': updated_doc, 'name': 'updated.pdf', 'active_version_id': uuid4(), 'available': True},
            {'id': deleted_doc, 'name': 'deleted.txt', 'active_version_id': deleted_version, 'available': False},
        ],
        cases=cases,
        outdated_citations=[{'document_id': updated_doc, 'citation_count': 3, 'message_count': 2}],
        latest_run=None,
    )

    assert report['stale_case_count'] == 2
    assert report['stale_evidence_count'] == 2
    impacts = {item['question']: item for item in report['stale_cases']}
    assert [item['status'] for item in impacts[cases[1].question]['affected_evidence']] == ['VERSION_CHANGED']
    assert [item['status'] for item in impacts[cases[2].question]['affected_evidence']] == ['SOURCE_UNAVAILABLE']
    assert report['updated_citation_count'] == 3
    assert report['updated_citations'][0]['message_count'] == 2


def test_knowledge_impact_keeps_conflict_and_insufficient_evidence_diagnoses_separate():
    conflict_id, insufficient_id = uuid4(), uuid4()
    latest_run = {
        'id': uuid4(),
        'created_at': datetime(2026, 10, 9, tzinfo=UTC),
        'cases': [
            {'id': str(conflict_id), 'question': '哪个日期是真的？', 'expected_behavior': 'CONFLICT'},
            {'id': str(insufficient_id), 'question': '员工电话是多少？', 'expected_behavior': 'INSUFFICIENT_EVIDENCE'},
        ],
        'results': [
            {'eval_case_id': conflict_id, 'answer_status': 'INSUFFICIENT_EVIDENCE'},
            {'eval_case_id': insufficient_id, 'answer_status': 'CONFLICT'},
        ],
    }

    report = build_knowledge_impact(documents=[], cases=[], outdated_citations=[], latest_run=latest_run)

    diagnosis = report['answer_classification']
    assert diagnosis['conflict'] == {'expected': 1, 'correct': 0, 'misclassified': 1, 'accuracy': 0.0}
    assert diagnosis['insufficient_evidence'] == {'expected': 1, 'correct': 0, 'misclassified': 1, 'accuracy': 0.0}
    assert {(item['expected_behavior'], item['actual_status']) for item in diagnosis['mismatches']} == {
        ('CONFLICT', 'INSUFFICIENT_EVIDENCE'),
        ('INSUFFICIENT_EVIDENCE', 'CONFLICT'),
    }


def test_knowledge_impact_handles_no_stale_records_and_no_completed_run():
    report = build_knowledge_impact(documents=[], cases=[], outdated_citations=[], latest_run=None)

    assert report['stale_cases'] == []
    assert report['updated_citations'] == []
    assert report['answer_classification'] is None
