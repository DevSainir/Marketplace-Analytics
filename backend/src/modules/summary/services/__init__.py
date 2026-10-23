"""Service layer for "Summary".

:mod:`.compose` is the arithmetic — pure functions over loaded DTOs — and
:mod:`.summary` is the orchestration that fetches those DTOs. Split so the
arithmetic can be tested against hand-written figures with no database in sight.
"""

from src.modules.summary.services.summary import SummaryService

__all__ = ["SummaryService"]
