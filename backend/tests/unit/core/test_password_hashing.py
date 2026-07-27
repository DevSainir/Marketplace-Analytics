"""Unit tests for password hashing and the opaque refresh-secret primitives.

These cover the properties the auth flow *depends* on rather than bcrypt's own
correctness: that a digest is salted (so equal passwords are not equal rows),
that verification is total (a corrupt stored digest must not 500 the login),
that the 72-byte bcrypt ceiling is refused rather than silently truncated, and
that refresh secrets are high-entropy and stored only as a digest.
"""

from __future__ import annotations

import pytest

from src.core.security import _BCRYPT_ROUNDS as SHIPPED_BCRYPT_ROUNDS
from src.core.security import (
    DUMMY_HASH,
    PASSWORD_MAX_BYTES,
    generate_refresh_secret,
    hash_password,
    hash_refresh_secret,
    verify_password,
)

# NOTE: the import above is evaluated at collection time, before the
# session-scoped fixture in tests/conftest.py lowers the work factor — so this
# name keeps the value that ships to production.


def test_password_verifies_against_its_own_digest() -> None:
    """The hash → verify round-trip accepts the original password."""
    digest = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-battery", digest) is True


def test_wrong_password_is_rejected() -> None:
    """A different password must not verify against the digest."""
    digest = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-stapler", digest) is False


def test_equal_passwords_produce_different_digests() -> None:
    """Digests are salted, so a database leak cannot be grouped by password."""
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second


def test_password_over_bcrypt_limit_is_refused() -> None:
    """Input past bcrypt's 72-byte window must raise, never be truncated.

    Silently hashing the first 72 bytes would let a user believe a 200-character
    passphrase protects them while the tail contributes nothing.
    """
    too_long = "a" * (PASSWORD_MAX_BYTES + 1)

    with pytest.raises(ValueError, match="72"):
        hash_password(too_long)


def test_multibyte_password_is_measured_in_bytes_not_characters() -> None:
    """The ceiling is a byte limit: Cyrillic hits it at ~36 characters."""
    thirty_seven_cyrillic_chars = "я" * 37  # 74 UTF-8 bytes

    with pytest.raises(ValueError, match="72"):
        hash_password(thirty_seven_cyrillic_chars)


def test_corrupt_stored_digest_fails_closed() -> None:
    """A malformed digest in storage is a failed match, not a crash.

    A legacy or truncated row must surface as "invalid credentials", not as a
    500 that tells an attacker which accounts have broken hashes.
    """
    assert verify_password("anything", "not-a-bcrypt-digest") is False


def test_dummy_hash_is_a_real_verifiable_digest() -> None:
    """The timing-mitigation digest must cost a real bcrypt verification.

    If ``DUMMY_HASH`` were a placeholder string, ``verify_password`` would take
    the cheap failure path and the unknown-user login would return measurably
    faster than a wrong-password login — re-opening the enumeration oracle the
    dummy exists to close.
    """
    assert verify_password("anything-at-all", DUMMY_HASH) is False
    assert DUMMY_HASH.startswith("$2b$")


def test_shipped_work_factor_stays_at_or_above_2_pow_12() -> None:
    """The deployed bcrypt cost must not be lowered below 2**12 rounds.

    ``tests/conftest.py`` patches the work factor down so the suite stays fast;
    :data:`SHIPPED_BCRYPT_ROUNDS` is bound at import time — before any fixture
    runs — so it still holds the value that actually ships. Without this guard a
    production downgrade would hide behind the test speed-up.
    """
    assert SHIPPED_BCRYPT_ROUNDS >= 12


def test_refresh_secrets_are_unique_per_issue() -> None:
    """Every issued refresh secret is fresh (no reuse across sessions)."""
    secrets_issued = {generate_refresh_secret() for _ in range(50)}

    assert len(secrets_issued) == 50


def test_refresh_secret_hash_is_deterministic_and_hides_the_secret() -> None:
    """The stored digest is stable for lookup yet is not the secret itself."""
    secret = generate_refresh_secret()

    digest = hash_refresh_secret(secret)

    assert digest == hash_refresh_secret(secret)
    assert secret not in digest
    assert len(digest) == 64
