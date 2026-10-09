from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.conversations import EvalCase


_DIAGNOSED_BEHAVIORS = ('CONFLICT', 'INSUFFICIENT_EVIDENCE')


def build_knowledge_impact(
    *,
    documents: Sequence[dict[str, object]],
    cases: Sequence[EvalCase],
    outdated_citations: Sequence[dict[str, object]],
    latest_run: dict[str, object] | None,
    outdated_citation_total: int | None = None,
) -> dict[str, object]:
    """Build a read-only impact report from current source and frozen eval data."""

    document_by_id = {_id(item['id']): item for item in documents}
    stale_cases: list[dict[str, object]] = []
    stale_evidence_count = 0

    for case in cases:
        affected = []
        for ref in case.evidence_refs:
            document = document_by_id.get(ref.document_id)
            if document is None:
                status = 'SOURCE_UNAVAILABLE'
                document_name = '资料已不存在'
                active_version_id = None
            else:
                document_name = str(document.get('name') or '未命名资料')
                active_version_id = document.get('active_version_id')
                if not document.get('available', False):
                    status = 'SOURCE_UNAVAILABLE'
                elif _optional_id(active_version_id) != ref.document_version_id:
                    status = 'VERSION_CHANGED'
                else:
                    continue
            stale_evidence_count += 1
            affected.append({
                'document_id': str(ref.document_id),
                'document_name': document_name,
                'labeled_version_id': str(ref.document_version_id),
                'active_version_id': str(active_version_id) if active_version_id else None,
                'status': status,
            })
        if affected:
            stale_cases.append({
                'eval_case_id': str(case.id),
                'question': case.question,
                'expected_behavior': case.expected_behavior,
                'affected_evidence': affected,
            })

    citations = [dict(item) for item in outdated_citations]
    citation_total = outdated_citation_total if outdated_citation_total is not None else sum(
        _count(item.get('citation_count')) for item in citations
    )
    return {
        'stale_case_count': len(stale_cases),
        'stale_evidence_count': stale_evidence_count,
        'stale_cases': stale_cases,
        'updated_citation_count': citation_total,
        'updated_citations': citations,
        'updated_citations_truncated': len(citations) >= 50,
        'answer_classification': _diagnose_answer_classification(latest_run),
    }


def _diagnose_answer_classification(latest_run: dict[str, object] | None) -> dict[str, object] | None:
    if latest_run is None:
        return None

    raw_cases = latest_run.get('cases')
    raw_results = latest_run.get('results')
    case_by_id = {
        str(case.get('id')): case
        for case in raw_cases if isinstance(case, dict)
    } if isinstance(raw_cases, list) else {}
    results = raw_results if isinstance(raw_results, list) else []
    totals = {behavior: {'expected': 0, 'correct': 0, 'misclassified': 0} for behavior in _DIAGNOSED_BEHAVIORS}
    mismatches = []

    for result in results:
        if not isinstance(result, dict):
            continue
        case = case_by_id.get(str(result.get('eval_case_id')))
        if case is None:
            continue
        expected = case.get('expected_behavior')
        if expected not in _DIAGNOSED_BEHAVIORS:
            continue
        actual = _status_value(result.get('answer_status'))
        totals[expected]['expected'] += 1
        if actual == expected:
            totals[expected]['correct'] += 1
            continue
        totals[expected]['misclassified'] += 1
        if len(mismatches) < 50:
            mismatches.append({
                'eval_case_id': str(case.get('id')),
                'question': str(case.get('question') or ''),
                'expected_behavior': expected,
                'actual_status': actual,
            })

    for behavior in _DIAGNOSED_BEHAVIORS:
        expected = totals[behavior]['expected']
        totals[behavior]['accuracy'] = totals[behavior]['correct'] / expected if expected else None

    run_created_at = latest_run.get('created_at')
    if isinstance(run_created_at, datetime):
        run_created_at = run_created_at.isoformat()
    return {
        'run_id': str(latest_run.get('id')) if latest_run.get('id') else None,
        'created_at': str(run_created_at) if run_created_at else None,
        'conflict': totals['CONFLICT'],
        'insufficient_evidence': totals['INSUFFICIENT_EVIDENCE'],
        'mismatches': mismatches,
        'mismatches_truncated': sum(item['misclassified'] for item in totals.values()) > len(mismatches),
    }


def _id(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_id(value: object) -> UUID | None:
    return _id(value) if value is not None else None


def _status_value(value: object) -> str:
    return str(getattr(value, 'value', value)) if value is not None else 'UNKNOWN'


def _count(value: object) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0
