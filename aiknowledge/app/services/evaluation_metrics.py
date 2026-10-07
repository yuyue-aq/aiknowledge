from hashlib import sha256

from app.domain.conversations import EvalCase, RetrievedChunk
from app.domain.evaluation import EvidenceRef
from app.domain.rag import AnswerStatus


def evidence_coverage(ref: EvidenceRef, chunks: list[RetrievedChunk]) -> tuple[bool, bool]:
    """Map versioned half-open source coordinates; reconstruct before hashing."""
    positions = {}
    conflict = False
    for chunk in chunks:
        if (chunk.document_id != ref.document_id or chunk.document_version_id != ref.document_version_id
            or chunk.source_block_id != ref.source_block_id or chunk.char_start is None or chunk.char_end is None):
            continue
        if len(chunk.content) != chunk.char_end - chunk.char_start:
            continue
        for pos in range(max(ref.char_start, chunk.char_start), min(ref.char_end, chunk.char_end)):
            char = chunk.content[pos - chunk.char_start]
            if pos in positions and positions[pos] != char:
                conflict = True
            positions[pos] = char
    full = len(positions) == ref.char_end - ref.char_start and not conflict
    if full:
        text = ''.join(positions[pos] for pos in range(ref.char_start, ref.char_end))
        full = sha256(text.encode('utf-8')).hexdigest() == ref.text_hash
    return bool(positions), full


def retrieval_metrics(case: EvalCase, chunks: list[RetrievedChunk], *, k: int, available_versions=None) -> dict[str, object]:
    selected = chunks[:k]
    expected = set(case.expected_document_ids)
    actual = {chunk.document_id for chunk in selected}
    labeled = case.answerable is not False and bool(expected)
    metrics = {'k': k, 'retrieved_count': len(selected),
        'document_recall_at_k': len(expected & actual)/len(expected) if labeled else None,
        'document_hit_at_k': float(bool(expected & actual)) if labeled else None,
        'evidence_recall_at_k': None, 'evidence_overlap_at_k': None}
    refs = [ref for ref in case.evidence_refs if ref.required]
    # Version drift is not an algorithmic miss. Exact evidence is measurable
    # only against the captured manifest in which all labels can be located.
    if refs and case.answerable is not False and available_versions is not None and all(
        ref.document_version_id in available_versions for ref in refs):
        coverage = [evidence_coverage(ref, selected) for ref in refs]
        metrics['evidence_recall_at_k'] = sum(full for _, full in coverage)/len(refs)
        metrics['evidence_overlap_at_k'] = sum(overlap for overlap, _ in coverage)/len(refs)
    return metrics


def refusal_correct(case: EvalCase, status: AnswerStatus) -> bool | None:
    if case.answerable is not False or case.expected_behavior is None:
        return None
    return status is not AnswerStatus.FAILED and status.value == case.expected_behavior
