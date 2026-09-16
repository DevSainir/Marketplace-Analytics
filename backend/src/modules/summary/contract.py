"""Public contract for the ``summary`` module.

Nothing consumes it yet — the surface is HTTP-only today — but a module without
a contract is a module other code will eventually reach into sideways, and the
boundary test requires one. The service and its response DTO are what a future
consumer would want; the composition helpers stay internal because their inputs
are this module's own choice of inputs, not a stable shape.
"""

from src.modules.summary.schemas import SummaryResponse
from src.modules.summary.services import SummaryService

__all__ = [
    "SummaryResponse",
    "SummaryService",
]
