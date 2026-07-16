"""Password hashing and JWT primitives.

This module owns every cryptographic operation in the platform:

* **Password hashing** via ``bcrypt`` (used directly — passlib is unmaintained)
  with a pre-computed ``DUMMY_HASH`` used to keep authentication timing
  constant for unknown users (timing-attack mitigation).
* **JWT issuance / verification** for short-lived access tokens.
* **Opaque refresh-token secret** generation and hashing for database-backed
  rotation.
* **Symmetric secret encryption** (Fernet) for third-party credentials stored
  at rest (per-workspace WildBerries API tokens).

It is transport-agnostic: it neither reads HTTP requests nor raises
``HTTPException``. Callers translate failures into responses.

.. warning::
   ``hash_password`` / ``verify_password`` burn ~100-300 ms of CPU by design.
   Async callers MUST offload them to a thread (``asyncio.to_thread``) —
   calling them inline blocks the entire event loop for every concurrent
   request.
"""

from __future__ import annotations

import enum
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings
from src.core.ids import uuid7

# bcrypt truncates input at 72 bytes; request schemas enforce this limit so no
# password is ever silently weakened past it.
PASSWORD_MAX_BYTES: int = 72

#: bcrypt work factor (2**12 iterations); tune per-env if profiling demands it.
_BCRYPT_ROUNDS: int = 12

# A real bcrypt digest of a throwaway password. When a login targets a
# non-existent user we still run ``verify_password`` against this hash so the
# CPU cost — and therefore the response latency — is indistinguishable from the
# valid-user path. Computed once at import time.
DUMMY_HASH: str = bcrypt.hashpw(
    b"dummy-password-for-constant-time-checks", bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
).decode("ascii")


class TokenType(enum.StrEnum):
    """Discriminates the JWTs the platform mints.

    Only ACCESS exists: refresh credentials are deliberately *opaque* random
    secrets (never JWTs), so a leaked signing key cannot mint long-lived
    sessions.
    """

    ACCESS = "access"


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Validated, decoded claims extracted from a JWT.

    Attributes:
        subject: The ``sub`` claim — the user's UUID as a string.
        token_type: The custom ``type`` claim distinguishing token kinds.
        jti: The unique token id (``jti`` claim), used to bind an access token
            to its refresh-token family row.
        issued_at: The ``iat`` claim as a timezone-aware datetime; compared
            against the per-user revocation watermark on every request.
        expires_at: The ``exp`` claim as a timezone-aware datetime.
    """

    subject: str
    token_type: TokenType
    jti: str
    issued_at: datetime
    expires_at: datetime


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt.

    CPU-bound (~100-300 ms): async callers must run this via
    ``asyncio.to_thread``.

    Args:
        plain_password: The user-supplied cleartext password (≤ 72 UTF-8
            bytes, enforced by the request schema).

    Returns:
        A salted bcrypt digest safe to persist.

    Raises:
        ValueError: If the encoded password exceeds bcrypt's 72-byte limit —
            hashing a silently truncated password would weaken it.
    """
    encoded = plain_password.encode("utf-8")
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password exceeds the bcrypt limit of {PASSWORD_MAX_BYTES} bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt digest.

    CPU-bound (~100-300 ms): async callers must run this via
    ``asyncio.to_thread``.

    Args:
        plain_password: The candidate cleartext password.
        password_hash: The stored digest (or :data:`DUMMY_HASH` for unknown
            users to preserve constant-time behaviour).

    Returns:
        ``True`` if the password matches, otherwise ``False``.
    """
    encoded = plain_password.encode("utf-8")[:PASSWORD_MAX_BYTES]
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        # Malformed/legacy digest in storage — treat as a failed match rather
        # than a 500; the caller surfaces a normal authentication error.
        return False


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


class SecretDecryptionError(Exception):
    """A stored ciphertext could not be decrypted with the configured key.

    Raised when ``FERNET_SECRET_KEY`` is missing, malformed, or differs from
    the key the secret was encrypted with (e.g. after an uncoordinated key
    rotation). Deliberately loud: silently returning an empty token would let a
    harvest run "successfully" with no credentials.
    """


def _fernet() -> Fernet:
    """Build the :class:`Fernet` cipher from the configured secret key.

    Constructed per call (cheap — key parsing only) so a process never caches a
    stale key object; the settings singleton is already immutable per process.

    Raises:
        SecretDecryptionError: If ``FERNET_SECRET_KEY`` is unset or not a valid
            urlsafe-base64 32-byte Fernet key.
    """
    if not settings.fernet_secret_key:
        raise SecretDecryptionError("FERNET_SECRET_KEY is not configured.")
    try:
        return Fernet(settings.fernet_secret_key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SecretDecryptionError("FERNET_SECRET_KEY is not a valid Fernet key.") from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a sensitive string for at-rest storage.

    Args:
        plaintext: The raw secret (e.g. a WB API bearer token).

    Returns:
        A urlsafe-base64 Fernet ciphertext (embeds timestamp + HMAC).

    Raises:
        SecretDecryptionError: If the encryption key is missing or malformed.
    """
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored Fernet ciphertext back into the raw secret.

    Args:
        ciphertext: The value produced by :func:`encrypt_secret`.

    Returns:
        The original plaintext secret.

    Raises:
        SecretDecryptionError: If the key is missing/malformed or does not
            match the key the ciphertext was produced with.
    """
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Stored secret cannot be decrypted with the configured FERNET_SECRET_KEY."
        ) from exc


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
    iat = raw.get("iat")
    exp = raw.get("exp")
    if not isinstance(subject, str) or not isinstance(jti, str) or exp is None or iat is None:
        return None

    return TokenPayload(
        subject=subject,
        token_type=expected_type,
        jti=jti,
        issued_at=datetime.fromtimestamp(int(iat), tz=UTC),
        expires_at=datetime.fromtimestamp(int(exp), tz=UTC),
    )
