"""Fixtures for the «Сводка» integration tests.

The miniature WB week lives in the finreports package because that is the module
whose arithmetic it was written to prove. It is re-exported rather than copied:
«Сводка» is derived from that same report, and a second fifteen-row financial
fixture is how the two halves would start disagreeing about what the week
contained.
"""

from tests.integration.finreports.conftest import seeded

__all__ = ["seeded"]
