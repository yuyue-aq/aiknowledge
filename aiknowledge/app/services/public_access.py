from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
from secrets import token_urlsafe
from uuid import UUID


class PublicSessionInvalidError(ValueError):
    """Raised when a browser public-session bearer cookie is unusable."""


class PublicSessionCodec:
    """Issue signed, short-lived sessions bound to a share-link identifier.

    The raw share token is intentionally absent.  API requests resolve the
    returned link UUID against the database every time, so revocation and
    category closure take effect immediately without a server-side cache.
    """

    VERSION = "v1"

    def __init__(
        self,
        *,
        secret: str,
        ttl_seconds: int,
        nonce_factory: Callable[[], str] = lambda: token_urlsafe(16),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not secret:
            raise ValueError("secret must not be empty")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds
        self._nonce_factory = nonce_factory
        self._clock = clock

    def issue(self, share_link_id: UUID) -> str:
        expires_at = int(self._now().timestamp()) + self._ttl_seconds
        nonce = self._nonce_factory()
        if not nonce or "." in nonce:
            raise ValueError("nonce_factory must return a non-empty dot-free value")
        payload = f"{self.VERSION}.{share_link_id}.{expires_at}.{nonce}"
        return f"{payload}.{self._sign(payload)}"

    def read_link_id(self, token: str) -> UUID:
        link_id, _ = self.read_session(token)
        return link_id

    def read_session(self, token: str) -> tuple[UUID, str]:
        try:
            version, raw_link_id, raw_expiry, nonce, signature = token.split(".")
            link_id = UUID(raw_link_id)
            expires_at = int(raw_expiry)
        except (AttributeError, TypeError, ValueError) as exc:
            raise PublicSessionInvalidError("访客会话无效。") from exc
        if version != self.VERSION or not nonce:
            raise PublicSessionInvalidError("访客会话无效。")
        payload = f"{version}.{raw_link_id}.{raw_expiry}.{nonce}"
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise PublicSessionInvalidError("访客会话无效。")
        if self._now().timestamp() >= expires_at:
            raise PublicSessionInvalidError("访客会话已过期。")
        return link_id, nonce

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
