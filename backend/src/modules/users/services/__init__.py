"""Business logic for authentication and JWT session rotation.

Split by responsibility once the single module approached the 500-line ceiling:
:mod:`.auth` is the service itself, :mod:`.breach` the family revocation that
runs on its own transaction, :mod:`.identity` the id→email lookup other modules
reach through ``contract.py``, :mod:`.lockout` the per-account login backoff,
and :mod:`.revocation` the two ways a session ends. Callers import from here exactly as before.
"""

from __future__ import annotations

from src.modules.users.services.auth import AuthService
from src.modules.users.services.breach import revoke_breached_family
from src.modules.users.services.identity import load_emails
from src.modules.users.services.lockout import LoginBackoff
from src.modules.users.services.revocation import end_family, revoke_all_sessions

__all__ = [
    "AuthService",
    "LoginBackoff",
    "end_family",
    "load_emails",
    "revoke_all_sessions",
    "revoke_breached_family",
]
