"""Password hashing and JWT primitives.

This module owns every cryptographic operation in the platform:

* **Password hashing** via ``passlib[bcrypt]`` with a pre-computed
  ``DUMMY_HASH`` used to keep authentication timing constant for unknown users
  (timing-attack mitigation).
* **JWT issuance / verification** for short-lived access tokens.
* **Opaque refresh-token secret** generation and constant-time hashing for
  database-backed rotation.

It is transport-agnostic: it neither reads HTTP requests nor raises
``HTTPException``. Callers translate failures into responses.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from src.core.config import settings
from src.core.ids import uuid7

# bcrypt work factor is intentionally the passlib default (12); tune per-env if
# hardware profiling demands it. ``deprecated="auto"`` enables transparent
# re-hashing when the scheme list evolves.
_pwd_context: CryptContext = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A real bcrypt digest of a throwaway password. When a login targets a
# non-existent user we still run ``verify_password`` against this hash so the
# CPU cost — and therefore the response latency — is indistinguishable from the
# valid-user path. Computed once at import time.
DUMMY_HASH: str = _pwd_context.hash("dummy-password-for-constant-time-checks")


class TokenType(enum.StrEnum):
    """Discriminates the JWTs the platform mints."""

    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Validated, decoded claims extracted from a JWT.

    Attributes:
        subject: The ``sub`` claim — the user's UUID as a string.
        token_type: The custom ``type`` claim distinguishing access/refresh.
        jti: The unique token id (``jti`` claim), used to bind an access token
            to its refresh-token family row.
        expires_at: The ``exp`` claim as a timezone-aware datetime.
    """

    subject: str
    token_type: TokenType
    jti: str
    expires_at: datetime


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt.

    Args:
        plain_password: The user-supplied cleartext password.

    Returns:
        A salted bcrypt digest safe to persist.
    """
    # passlib is untyped (mypy treats returns as Any); coerce explicitly.
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt digest.

    Args:
        plain_password: The candidate cleartext password.
        password_hash: The stored digest (or :data:`DUMMY_HASH` for unknown
            users to preserve constant-time behaviour).

    Returns:
        ``True`` if the password matches, otherwise ``False``.
    """
    # passlib is untyped (mypy treats returns as Any); coerce explicitly.
    return bool(_pwd_context.verify(plain_password, password_hash))


def generate_refresh_secret() -> str:
    """Return a cryptographically strong, URL-safe opaque refresh secret.

    The raw secret is delivered to the client (via HttpOnly cookie) exactly
    once; only its :func:`hash_refresh_secret` digest is stored server-side.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_secret(secret: str) -> str:
    """Hash an opaque refresh secret for at-rest storage.

    A fast SHA-256 is appropriate here (unlike passwords) because the secret is
    already high-entropy; this avoids paying bcrypt cost on every token refresh.

    Args:
        secret: The raw refresh secret.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_refresh_secret(secret: str, secret_hash: str) -> bool:
    """Constant-time compare a presented refresh secret against its digest."""
    return hmac.compare_digest(hash_refresh_secret(secret), secret_hash)


def create_access_token(
    *,
    user_id: uuid.UUID,
    jti: uuid.UUID | None = None,
) -> tuple[str, datetime]:
    """Mint a signed, short-lived JWT access token.

    Args:
        user_id: The subject user's primary key.
        jti: Optional explicit token id; a fresh UUID is generated when omitted.

    Returns:
        A ``(encoded_jwt, expires_at)`` tuple. ``expires_at`` is timezone-aware
        (UTC) so callers can set cookie/response metadata precisely.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    # Use UUIDv7 to match every other id in the platform (see src.core.ids).
    # In practice the caller (AuthService._issue_pair) always supplies `jti`;
    # this fallback keeps standalone calls consistent rather than mixing in v4.
    token_id = jti or uuid7()
    claims: dict[str, object] = {
        "sub": str(user_id),
        "type": TokenType.ACCESS.value,
        "jti": str(token_id),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(
        claims,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded, expires_at


def decode_token(
    token: str,
    *,
    expected_type: TokenType,
) -> TokenPayload | None:
    """Decode and validate a JWT, enforcing signature, expiry, and type.

    Args:
        token: The raw encoded JWT string.
        expected_type: The token ``type`` claim that must match.

    Returns:
        A :class:`TokenPayload` on success, or ``None`` if the token is
        invalid, expired, or of the wrong type. Returning ``None`` (rather than
        raising) keeps this primitive transport-neutral.
    """
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None

    if raw.get("type") != expected_type.value:
        return None

    subject = raw.get("sub")
    jti = raw.get("jti")
    exp = raw.get("exp")
    if not isinstance(subject, str) or not isinstance(jti, str) or exp is None:
        return None

    return TokenPayload(
        subject=subject,
        token_type=expected_type,
        jti=jti,
        expires_at=datetime.fromtimestamp(int(exp), tz=UTC),
    )
