"""Business logic for authentication and JWT session rotation.

Split by responsibility once the single module approached the 500-line ceiling:
:mod:`.auth` is the service itself, :mod:`.breach` the family revocation that
runs on its own transaction, :mod:`.identity` the id→email lookup other modules
reach through ``contract.py``. Callers import from here exactly as before.
"""

from __future__ import annotations

from src.modules.users.services.auth import AuthService
from src.modules.users.services.breach import revoke_breached_family
from src.modules.users.services.identity import load_emails

__all__ = ["AuthService", "load_emails", "revoke_breached_family"]
