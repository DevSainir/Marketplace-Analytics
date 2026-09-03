"""Business logic for authentication and JWT session rotation.

Split by responsibility once the single module approached the 500-line ceiling:
:mod:`.auth` is the service itself, :mod:`.breach` the family revocation that
runs on its own transaction, :mod:`.identity` the id→email lookup other modules
reach through ``contract.py``, :mod:`.lockout` the per-account login backoff,
:mod:`.registration` creating an account (which is not a session, and carries
the rule that the password is applied at CONFIRMATION rather than at signup),
and :mod:`.revocation` the two ways a session ends. :mod:`.recovery` and
:mod:`.verification` are email confirmation and password reset (P1.6).
Callers import from here exactly as before.
"""

from __future__ import annotations

from src.modules.users.services.auth import AuthService
from src.modules.users.services.breach import revoke_breached_family
from src.modules.users.services.identity import load_emails
from src.modules.users.services.lockout import LoginBackoff
from src.modules.users.services.recovery import AccountRecoveryService
from src.modules.users.services.registration import RegistrationOutcome, RegistrationService
from src.modules.users.services.revocation import end_family, revoke_all_sessions
from src.modules.users.services.verification import VerificationService

__all__ = [
    "AccountRecoveryService",
    "AuthService",
    "LoginBackoff",
    "RegistrationOutcome",
    "RegistrationService",
    "VerificationService",
    "end_family",
    "load_emails",
    "revoke_all_sessions",
    "revoke_breached_family",
]
