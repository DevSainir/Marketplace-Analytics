"""Component tests for «Загрузить отчёт» (``/v1/finreports/settlement-uploads``).

The route's whole job is to answer at once: is this WB's weekly report, which
one, and is another upload of the workspace still being read — and then hand the
file to the worker. What the worker does with it is the integration tier's
(``tests/integration/finreports/test_settlement_upload_flow.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_settlement_upload_service
from src.modules.finreports.models import SettlementUpload, UploadStatus
from src.modules.finreports.services import SettlementUploadService
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository
from tests.support.wb_weekly_report import (
    FILENAME,
    REPORT_ID,
    weekly_row,
    weekly_workbook,
    weekly_zip,
)

URL = "/api/v1/finreports/settlement-uploads"


class _FakeUploads:
    """In-memory uploads, keyed by id, with the repository's three questions."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, SettlementUpload] = {}
        self.busy = False

    async def create(self, upload: SettlementUpload) -> SettlementUpload:
        upload.id = uuid.uuid4()
        self.rows[upload.id] = upload
        return upload

    async def in_flight(self, *, workspace_id: uuid.UUID) -> bool:
        return self.busy

    async def get(
        self, *, workspace_id: uuid.UUID, upload_id: uuid.UUID
    ) -> SettlementUpload | None:
        upload = self.rows.get(upload_id)
        return upload if upload and upload.workspace_id == workspace_id else None


class _SpyTask:
    """Stands in for ``process_settlement_upload.delay``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def uploads() -> _FakeUploads:
    return _FakeUploads()


@pytest.fixture(autouse=True)
def task(monkeypatch: pytest.MonkeyPatch) -> _SpyTask:
    """Nothing reaches a broker."""
    spy = _SpyTask()
    monkeypatch.setattr(
        "src.modules.finreports.routers.settlement_upload.process_settlement_upload", spy
    )
    return spy


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    uploads: _FakeUploads,
) -> None:
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(
        get_settlement_upload_service,
        SettlementUploadService(upload_repo=uploads),  # type: ignore[arg-type]
    )


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


def _file(name: str = FILENAME, data: bytes | None = None) -> dict[str, Any]:
    body = data if data is not None else weekly_zip(weekly_workbook([weekly_row()]))
    return {"file": (name, body, "application/zip")}


async def test_wbs_file_is_queued_for_the_caller_own_workspace(
    client: httpx.AsyncClient, headers: dict[str, str], workspace: Workspace, task: _SpyTask
) -> None:
    """Answered at once with the report it is, and handed to the worker by id."""
    response = await client.post(URL, headers=headers, files=_file())

    body = response.json()
    assert response.status_code == 202
    assert (body["status"], body["report_id"]) == ("queued", REPORT_ID)
    assert task.calls == [{"upload_id": body["id"]}]


async def test_a_file_that_is_not_wbs_report_is_refused_before_anything_is_queued(
    client: httpx.AsyncClient, headers: dict[str, str], task: _SpyTask
) -> None:
    """A wrong file costs the seller a message, not a minute of the worker."""
    response = await client.post(URL, headers=headers, files=_file("costs.csv", b"a,b\n1,2\n"))

    assert response.status_code == 422
    assert task.calls == []


async def test_a_second_upload_waits_for_the_first(
    client: httpx.AsyncClient, headers: dict[str, str], uploads: _FakeUploads, task: _SpyTask
) -> None:
    """One file in flight per workspace: two of the same week would race to write it."""
    uploads.busy = True

    response = await client.post(URL, headers=headers, files=_file())

    assert response.status_code == 409
    assert task.calls == []


async def test_the_poll_reads_only_the_callers_own_uploads(
    client: httpx.AsyncClient, headers: dict[str, str], uploads: _FakeUploads
) -> None:
    """Another workspace's upload is a 404, the same as one that does not exist."""
    stranger = SettlementUpload(
        id=uuid.uuid4(), workspace_id=uuid.uuid4(), status=UploadStatus.WRITTEN
    )
    uploads.rows[stranger.id] = stranger

    response = await client.get(f"{URL}/{stranger.id}", headers=headers)

    assert response.status_code == 404


async def test_the_poll_says_how_the_upload_ended(
    client: httpx.AsyncClient, headers: dict[str, str], workspace: Workspace, uploads: _FakeUploads
) -> None:
    """The page shows the worker's own words when the status settles."""
    done = SettlementUpload(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        status=UploadStatus.ALREADY_HELD,
        message="Этот отчёт у нас уже есть — совпадает с файлом до строки.",
        rows_total=3257,
        rows_written=0,
    )
    uploads.rows[done.id] = done

    response = await client.get(f"{URL}/{done.id}", headers=headers)

    assert response.json()["status"] == "already_held"
    assert response.json()["message"].startswith("Этот отчёт у нас уже есть")


async def test_the_upload_requires_authentication(client: httpx.AsyncClient) -> None:
    """No session, no upload."""
    response = await client.post(URL, files=_file())

    assert response.status_code == 401
