from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.public_access import PublicSessionCodec, PublicSessionInvalidError


def test_public_session_cookie_does_not_contain_raw_share_token_and_rejects_tampering() -> None:
    link_id = uuid4()
    codec = PublicSessionCodec(
        secret="test-public-session-secret",
        ttl_seconds=600,
        nonce_factory=lambda: "fixed-nonce",
        clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
    )

    token = codec.issue(link_id)

    assert str(link_id) in token
    assert "only-returned-once-token" not in token
    assert codec.read_link_id(token) == link_id
    with pytest.raises(PublicSessionInvalidError):
        codec.read_link_id(token[:-1] + ("a" if token[-1] != "a" else "b"))


def test_public_session_cookie_expires() -> None:
    issued_at = datetime(2026, 9, 11, tzinfo=UTC)
    codec = PublicSessionCodec(
        secret="test-public-session-secret",
        ttl_seconds=60,
        nonce_factory=lambda: "fixed-nonce",
        clock=lambda: issued_at,
    )
    token = codec.issue(uuid4())
    expired_codec = PublicSessionCodec(
        secret="test-public-session-secret",
        ttl_seconds=60,
        clock=lambda: issued_at + timedelta(seconds=61),
    )

    with pytest.raises(PublicSessionInvalidError, match="过期"):
        expired_codec.read_link_id(token)
