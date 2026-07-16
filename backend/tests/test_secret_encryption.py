"""Unit tests for the Fernet secret-encryption helpers (workspace WB tokens)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.core.config import settings
from src.core.security import SecretDecryptionError, decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret survives the encrypt -> decrypt roundtrip unchanged."""
    monkeypatch.setattr(settings, "fernet_secret_key", Fernet.generate_key().decode())
    token = "eyJhbGciOiJFUzI1NiJ9.some-wb-token-payload"  # noqa: S105 — test fixture, not a credential
    ciphertext = encrypt_secret(token)
    assert ciphertext != token
    assert decrypt_secret(ciphertext) == token


def test_ciphertext_differs_from_plaintext_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fernet ciphertexts are salted — equal secrets produce distinct ciphertexts."""
    monkeypatch.setattr(settings, "fernet_secret_key", Fernet.generate_key().decode())
    assert encrypt_secret("same-secret") != encrypt_secret("same-secret")


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset FERNET_SECRET_KEY must fail loudly, not return garbage."""
    monkeypatch.setattr(settings, "fernet_secret_key", "")
    with pytest.raises(SecretDecryptionError):
        encrypt_secret("anything")


def test_malformed_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-Fernet key is a configuration error, not a silent no-op."""
    monkeypatch.setattr(settings, "fernet_secret_key", "not-a-fernet-key")
    with pytest.raises(SecretDecryptionError):
        encrypt_secret("anything")


def test_wrong_key_cannot_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ciphertext from one key must not decrypt under another (rotation guard)."""
    monkeypatch.setattr(settings, "fernet_secret_key", Fernet.generate_key().decode())
    ciphertext = encrypt_secret("secret")
    monkeypatch.setattr(settings, "fernet_secret_key", Fernet.generate_key().decode())
    with pytest.raises(SecretDecryptionError):
        decrypt_secret(ciphertext)
