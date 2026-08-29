"""Public contract for the Users module.

Other modules that need identity primitives (e.g. resolving the current user)
import **only** from here — never from ``services``/``repos``/``models``. This
keeps the module's internals free to change behind a stable surface, enforcing
the "no horizontal imports" architecture rule.
"""

from __future__ import annotations

from src.core.deps import CurrentUserId
from src.modules.users.deps import CurrentUser, DevUser, require_dev_role
from src.modules.users.models import ROLE_DEV, ROLE_USER
from src.modules.users.schemas import UserRead
from src.modules.users.services import load_emails

__all__ = [
    "ROLE_DEV",
    "ROLE_USER",
    "CurrentUser",
    "CurrentUserId",
    "DevUser",
    "UserRead",
    "load_emails",
    "require_dev_role",
]
