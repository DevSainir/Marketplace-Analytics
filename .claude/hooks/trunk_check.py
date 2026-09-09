#!/usr/bin/env python3
"""Tell a session that started outside `main` how to get back onto it.

Wired as a SessionStart hook in .claude/settings.json. It is aimed at the
mechanism that actually produced the stray branches in this repo: harness
worktree isolation, which drops a session into `.claude/worktrees/<name>` on a
`claude/<name>` branch before the session's first message — no model ever types
`git checkout -b`, so a rule that only forbids that command never fires.

Silent on `main`, and silent on the Release Please branch, which is the one
legitimate branch here.
"""

import json
import os
import subprocess
import sys


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ("git", *args), capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch in {"main", "HEAD"}:
        return 0
    if branch.startswith("release-please--branches--"):
        return 0

    in_worktree = os.path.sep + os.path.join(".claude", "worktrees") in os.getcwd()
    where = (
        f"an isolated worktree ({os.getcwd()})"
        if in_worktree
        else "a branch outside `main`"
    )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"WORKFLOW WARNING: this session is on branch `{branch}`, in {where}. "
                "This repository is trunk-based: work lands on `main`, and `main` IS "
                "the working branch — nothing here justifies isolation, including the "
                "harness's own worktree isolation, which is what put you here. "
                "Before you do anything else, say so to whoever asked, and land the "
                "work on `main` in the primary checkout instead. Uncommitted work in a "
                "worktree has no reflog behind it, so it is the case that loses data — "
                "commit or move it before the worktree is removed. Recovery, and the "
                "one legitimate exception (the Release Please branch), are in "
                ".claude/skills/git-workflow/SKILL.md."
            ),
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
