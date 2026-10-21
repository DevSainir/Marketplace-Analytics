#!/usr/bin/env python3
"""Check docs/JOURNAL.md, or build the journal page from it.

    python3 scripts/journal_page.py --check
    python3 scripts/journal_page.py --out <path>/journal.html

The page is one HTML file built from the template scripts/journal_page.html,
with the rows embedded as JSON. It is only ever rebuilt from the journal,
never edited by hand.

Standard library only, so it runs without the backend's environment.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "docs" / "JOURNAL.md"
TEMPLATE = Path(__file__).with_suffix(".html")
PLACEHOLDER = "__JOURNAL_DATA__"
REPO_URL = "https://github.com/DevSainir/Marketplace-Analytic-Service"

HEADER = ("Date", "Task", "Area", "Type", "Size", "Why", "Commits")
AREAS = (
    "Monitoring",
    "P&L",
    "Advertising",
    "A/B tests",
    "Summary",
    "Heatmap",
    "UI",
    "Access",
    "Infrastructure",
    "Security",
    "Process",
)
TYPES = ("feature", "improvement", "bug", "infrastructure", "docs")
SIZES = ("S", "M", "L")
DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
COMMIT = re.compile(r"^`([0-9a-f]{7,40})`$")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def split_row(line: str) -> list[str]:
    body = line.strip()[1:-1]
    return [cell.strip().replace("\\|", "|") for cell in UNESCAPED_PIPE.split(body)]


def parse(text: str) -> tuple[list[dict[str, object]], list[str]]:
    """Return the rows and every problem found, each with its line number."""
    lines = text.splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith("|") and tuple(split_row(line)) == HEADER
        ),
        None,
    )
    if start is None:
        return [], [f"no table whose header is | {' | '.join(HEADER)} |"]

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    previous: dt.date | None = None
    for number, line in enumerate(lines[start + 2 :], start=start + 3):
        if not line.startswith("|"):
            break
        cells = split_row(line)
        problems: list[str] = []
        if len(cells) != len(HEADER):
            errors.append(f"line {number}: {len(cells)} cells, expected {len(HEADER)}")
            continue
        date_s, title, area, kind, size, why, commits_s = cells

        match = DATE.match(date_s)
        date: dt.date | None = None
        if match:
            with contextlib.suppress(ValueError):
                date = dt.date(int(match[1]), int(match[2]), int(match[3]))
        if date is None:
            problems.append(f"date {date_s!r} is not YYYY-MM-DD")
        elif previous is not None and date > previous:
            problems.append(f"{date_s} is newer than the row above; new rows go on top")
        if not title:
            problems.append("empty title")
        if area not in AREAS:
            problems.append(f"area {area!r} is not one of {', '.join(AREAS)}")
        if kind not in TYPES:
            problems.append(f"type {kind!r} is not one of {', '.join(TYPES)}")
        if size not in SIZES:
            problems.append(f"size {size!r} is not S, M or L")
        if not why:
            problems.append("empty Why")

        commits: list[str] = []
        for token in commits_s.split():
            commit = COMMIT.match(token)
            if not commit:
                problems.append(f"commit {token!r} is not a `hash` in backticks")
                continue
            sha = commit[1]
            if sha in seen:
                problems.append(f"commit {sha} is already on line {seen[sha]}")
            seen[sha] = number
            commits.append(sha)
        # An empty Commits cell is allowed: a few reconstructed rows describe work whose
        # commits only touched files that are not part of this repository.

        errors.extend(f"line {number}: {problem}" for problem in problems)
        if date is not None:
            previous = date
            rows.append(
                {
                    "date": date.isoformat(),
                    "title": title,
                    "area": area,
                    "type": kind,
                    "size": size,
                    "why": why,
                    "commits": commits,
                }
            )
    return rows, errors


def unreachable_commits(shas: list[str]) -> list[str]:
    """The hashes that are not in HEAD's history; empty when git is not available.

    Reachability rather than existence: a rebase leaves the old commits behind
    as dangling objects, so a row written before it would still resolve.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(ROOT), "rev-list", "HEAD"],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    history = result.stdout.split()
    prefixes = {
        length: {full[:length] for full in history} for length in {len(sha) for sha in shas}
    }
    return [sha for sha in shas if sha not in prefixes[len(sha)]]


def build(rows: list[dict[str, object]]) -> str:
    data = {
        "generated": dt.date.today().isoformat(),
        "repo": REPO_URL,
        "areas": AREAS,
        "types": TYPES,
        "sizes": SIZES,
        "rows": rows,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="validate the journal and exit")
    group.add_argument("--out", type=Path, help="write the page to this file")
    args = parser.parse_args()

    rows, errors = parse(JOURNAL.read_text(encoding="utf-8"))
    shas = [sha for row in rows for sha in row["commits"]]  # type: ignore[attr-defined]
    errors.extend(f"commit {sha} is not in HEAD's history" for sha in unreachable_commits(shas))
    if errors:
        print(f"{JOURNAL.relative_to(ROOT)}:", *errors, sep="\n  ", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(build(rows), encoding="utf-8")
        print(f"{len(rows)} tasks -> {args.out}")
    else:
        print(f"{len(rows)} tasks, journal is well-formed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
