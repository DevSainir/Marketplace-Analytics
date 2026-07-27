"""Business-logic layer for the ``finreports`` module.

Two services, mirroring the monitoring split:

* :class:`IngestionService` — write side: harvest the finance report, the tariff
  calendar and the baseline dimensions into the ``finreports`` schema.
  dispute-ready evidence from stored facts.

implemented already (it needs no WB token): it is the fundamental logic the rest
of the module is built to feed.
"""

from src.modules.finreports.services.ingestion import IngestionService

