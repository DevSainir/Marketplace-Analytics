"""Public contract for the Users module.

Other modules that need identity primitives (e.g. resolving the current user)
import **only** from here — never from ``services``/``repos``/``models``. This
keeps the module's internals free to change behind a stable surface, enforcing
the "no horizontal imports" architecture rule.
"""

from __future__ import annotations

from src.core.deps import CurrentUserId
from src.modules.users.schemas import UserRead

__all__ = ["CurrentUserId", "UserRead"]
