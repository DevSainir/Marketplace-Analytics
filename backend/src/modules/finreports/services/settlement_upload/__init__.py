"""Hand-uploaded weekly reports: read the file, compare it, stand it in, hand it over.

* :mod:`.workbook` — WB's xlsx into settlement rows.
* :mod:`.compare` — two sets of rows as multisets, with no shared id.
* :mod:`.service` — the request side: accept and queue, report status.
* :mod:`.reconcile` — the API serves the report: compare, then hand over.
* :mod:`.wording` — what the seller is told.

The worker's half is :mod:`src.modules.finreports.tasks.settlement_upload`.
"""

from src.modules.finreports.services.settlement_upload.service import SettlementUploadService

__all__ = ["SettlementUploadService"]
