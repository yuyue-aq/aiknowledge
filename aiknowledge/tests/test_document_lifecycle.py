from __future__ import annotations

import pytest

from app.domain.documents import (
    DocumentStatus,
    DocumentTransitionError,
    DocumentVersionStatus,
    advance_document_status,
    advance_document_version_status,
    is_document_retrievable,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DocumentStatus.PROCESSING, DocumentStatus.READY),
        (DocumentStatus.PROCESSING, DocumentStatus.FAILED),
        (DocumentStatus.PROCESSING, DocumentStatus.DELETED),
        (DocumentStatus.FAILED, DocumentStatus.PROCESSING),
        (DocumentStatus.FAILED, DocumentStatus.DELETED),
        (DocumentStatus.READY, DocumentStatus.DELETED),
    ],
)
def test_document_lifecycle_allows_only_safe_transitions(
    current: DocumentStatus, target: DocumentStatus
) -> None:
    assert advance_document_status(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DocumentStatus.READY, DocumentStatus.PROCESSING),
        (DocumentStatus.DELETED, DocumentStatus.PROCESSING),
        (DocumentStatus.DELETED, DocumentStatus.READY),
        (DocumentStatus.PROCESSING, DocumentStatus.PROCESSING),
    ],
)
def test_document_lifecycle_rejects_unsafe_or_terminal_transitions(
    current: DocumentStatus, target: DocumentStatus
) -> None:
    with pytest.raises(DocumentTransitionError):
        advance_document_status(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DocumentVersionStatus.PROCESSING, DocumentVersionStatus.READY),
        (DocumentVersionStatus.PROCESSING, DocumentVersionStatus.FAILED),
        (DocumentVersionStatus.FAILED, DocumentVersionStatus.PROCESSING),
    ],
)
def test_document_version_lifecycle_supports_retry_without_touching_active_document(
    current: DocumentVersionStatus, target: DocumentVersionStatus
) -> None:
    assert advance_document_version_status(current, target) is target


def test_only_ready_document_with_active_version_is_retrievable() -> None:
    assert is_document_retrievable(DocumentStatus.READY, active_version_id="version-1")
    assert not is_document_retrievable(DocumentStatus.READY, active_version_id=None)
    assert not is_document_retrievable(
        DocumentStatus.PROCESSING, active_version_id="version-1"
    )
    assert not is_document_retrievable(
        DocumentStatus.FAILED, active_version_id="version-1"
    )
    assert not is_document_retrievable(
        DocumentStatus.DELETED, active_version_id="version-1"
    )
