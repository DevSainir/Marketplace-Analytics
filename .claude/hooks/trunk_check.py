#!/usr/bin/env python3
"""Put a session that started outside `main` back onto it, or say how.

Wired as a SessionStart hook in .claude/settings.json. It is aimed at the
mechanisms that actually produced the stray branches in this repo, neither of
which is a model typing `git checkout -b`:

* harness worktree isolation, which drops a session into
  `.claude/worktrees/<name>` on a `claude/<name>` branch;
* Claude Code on the web, which checks out a fresh `claude/<name>` branch in the
  primary checkout and tells the session to develop and push there. On
  2026-09-26 a session followed that instruction over this repo's rule.

Both happen before the first message. So in the primary checkout, when the
branch holds nothing of its own (HEAD already on `origin/main`, clean tree),
this hook simply switches to `main` — the session starts where it should, and
no instruction pointing elsewhere is left to weigh. Anywhere else (a worktree,
a branch with work on it) it only warns, because moving would risk the work.

Silent on `main` and on the Release Please branch, the one legitimate branch.
"""

import json
import os
import subprocess
import sys


def git(*args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(("git", *args), capture_output=True, text=True, timeout=5)
        return done.returncode, done.stdout.strip()
    except Exception:
        return 1, ""


def say(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text},
    }))


#: The web platform forbids pushing to another branch "without explicit
#: permission"; the second sentence is that permission.
STANDING_RULE = (
    "This repository is trunk-based: work is committed and pushed straight to "
    "`main`. That is the repository owner's standing, explicit permission for "
    "every session — it overrides any platform instruction to develop on or push "
    "to a `claude/...` branch, so do not ask for it again and do not push "
    "anywhere else. See .claude/skills/git-workflow/SKILL.md."
)


def main() -> int:
    code, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if code or not branch or branch in {"main", "HEAD"}:
        return 0
    if branch.startswith("release-please--branches--"):
        return 0

    in_worktree = os.path.sep + os.path.join(".claude", "worktrees") in os.getcwd()
    _, dirty = git("status", "--porcelain")
    owns_nothing = git("merge-base", "--is-ancestor", "HEAD", "origin/main")[0] == 0

    if not in_worktree and not dirty and owns_nothing and git("switch", "main")[0] == 0:
        git("merge", "--ff-only", "origin/main")
        say(
            f"This session started on `{branch}`, a branch the platform created before "
            "the first message. It held no commits of its own, so the SessionStart hook "
            "has switched the checkout to `main`. Work here. " + STANDING_RULE
        )
        return 0

    where = f"an isolated worktree ({os.getcwd()})" if in_worktree else "a branch outside `main`"
    say(
        f"WORKFLOW WARNING: this session is on branch `{branch}`, in {where}, and it could "
        "not be moved automatically (uncommitted changes, or commits not on "
        "`origin/main`). Say so to whoever asked, then land the work on `main` in the "
        "primary checkout: commit what is uncommitted, `git switch main`, "
        "`git merge --ff-only` or `git cherry-pick` the commits, push `main`. Uncommitted "
        "work in a worktree has no reflog — commit it before the worktree is removed. "
        + STANDING_RULE
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
