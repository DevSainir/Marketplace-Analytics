"""No Russian anywhere in the repository except the labels Wildberries itself sends.

The product is in English end to end — UI copy, API messages, alert text,
docs, comments, test names. It used to be the other way round: the interface
was Russian and a test failed on an English message, so the rule has to be
stated as strongly in the new direction or Russian drifts back one quoted
label at a time.

**What may stay Russian, and why it must.** WB serves its own data in Russian,
and parts of this codebase classify that data by exact string: a settlement
row is a sale because its ``supplier_oper_name`` is the Russian word for one,
a weekly report is parsed by its Russian column headers, an advertising
write-off is a bonus because WB names its payment type so. Translating any of
those does not raise — it produces a P&L in which the operation is simply
never counted. Those literals are listed in ``_WB_LABELS``, file by file, each
with the reason; nothing else may hold Cyrillic.

Real sellers' data — product names, warehouses, penalty reasons — still
arrives in Russian at runtime. That is data, not code, and never reaches a
tracked file.

**How the files are found.** Asking git, because "what would be published"
is a question only git can answer: tracked files plus untracked ones that are
not ignored, so a new file is checked before anyone remembers to add it.
"""

from __future__ import annotations

import fnmatch
import pathlib
import re
import shutil
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[4]

#: Any Cyrillic letter. Written as an escape so this file passes its own test.
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")

#: Files that must keep WB's own Russian labels, with the reason for each.
_WB_LABELS: dict[str, str] = {
    "backend/src/modules/finreports/constants.py": (
        "supplier_oper_name / doc_type_name / bonus_type_name values the P&L classifies on"
    ),
    "backend/src/modules/finreports/services/settlement_upload/workbook.py": (
        "column headers of the weekly report workbook WB's seller portal exports"
    ),
    "backend/src/modules/monitoring/models/advertising.py": (
        "WB's advertising paymentType values that split bonuses from cash"
    ),
    "backend/src/core/config/storefront.py": (
        "the regionName values of the Moscow region in WB's order feed"
    ),
    "backend/alembic/versions/b3d7f18c05ae_pnl_partial_indexes.py": (
        "a partial index whose predicate is WB's sale operation name"
    ),
    "backend/tests/support/wb_labels.py": "the WB labels the tests feed in, spelled out",
    "backend/tests/support/wb_weekly_report.py": (
        "the column headers and file name of the weekly report workbook, as WB writes them"
    ),
}

#: The translation in progress, one entry per piece of work; each entry goes
#: with the commit that translates it, and the list goes with the last one.
_IN_TRANSLATION: dict[str, tuple[str, ...]] = {
    # Regenerated from the backend's OpenAPI text once every module is done.
    "api types": ("frontend/src/core/api/schema.d.ts",),
    # Asserts on messages of several modules at once.
    "cross-module": ("backend/tests/unit/core/test_tenant_resource_bounds.py",),
    "finreports": (
        "backend/src/modules/finreports/*",
        "backend/tests/*/finreports/*",
        "frontend/src/modules/finreports/*",
    ),
    "ab_tests": (
        "backend/src/modules/ab_tests/*",
        "backend/tests/*/ab_tests/*",
        "frontend/src/modules/abTests/*",
    ),
    "guide": ("backend/src/modules/guide/*", "backend/tests/*/guide/*"),
    "operations": (
        "backend/docker/*",
        "backend/scripts/*",
        "backend/alembic/*",
        "backend/.env.example",
        "backend/pyproject.toml",
        "frontend/docker/*",
        "tests/*",
    ),
    "docs": ("docs/*", ".claude/*", "README.md", "CLAUDE.md"),
}


def _repository_files() -> list[str]:
    """Every file git would publish: tracked, plus untracked and not ignored."""
    git = shutil.which("git")
    assert git, "git is required to know which files belong to the repository"
    # S603: the executable comes from `shutil.which` and the arguments are
    # literals.
    listed = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=_ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    return sorted({path.decode() for path in listed if path and (_ROOT / path.decode()).is_file()})


def _russian_lines(path: str) -> list[int]:
    """Line numbers holding Cyrillic; none for a file that is not UTF-8 text."""
    try:
        text = (_ROOT / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return [number for number, line in enumerate(text.splitlines(), 1) if _CYRILLIC.search(line)]


def _in_translation(path: str) -> bool:
    """Whether the file belongs to a piece of the translation still to do."""
    patterns = [pattern for unit in _IN_TRANSLATION.values() for pattern in unit]
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def test_the_scan_sees_the_whole_repository() -> None:
    """Guard the guard: a listing that came back nearly empty checks nothing."""
    # Arrange / Act
    files = _repository_files()

    # Assert — the exact count moves with the code; its order of magnitude does not.
    assert len(files) > 1000
    assert "backend/main.py" in files
    assert "frontend/src/main.js" in files


def test_nothing_outside_the_wb_labels_is_in_russian() -> None:
    """Cyrillic appears only in the files that must match WB's own text."""
    # Arrange
    allowed = set(_WB_LABELS)

    # Act
    offenders = [
        f"{path}:{line}"
        for path in _repository_files()
        if path not in allowed and not _in_translation(path)
        for line in _russian_lines(path)
    ]

    # Assert
    assert offenders == [], (
        "Russian text outside WB's own labels — translate it, or, if it is a "
        "value WB sends and the code matches on, add the file to _WB_LABELS "
        "with the reason:\n" + "\n".join(offenders)
    )


def test_every_wb_label_file_still_holds_wb_labels() -> None:
    """An entry whose file no longer has any Cyrillic is a stale exemption.

    Left in place it would let Russian back into that file unnoticed, so it
    has to go the moment the labels move or disappear.
    """
    # Arrange / Act
    stale = [path for path in _WB_LABELS if not _russian_lines(path)]

    # Assert
    assert stale == [], "No WB label left in:\n" + "\n".join(stale)
