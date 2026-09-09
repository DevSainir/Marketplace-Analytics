#!/usr/bin/env python3
"""Refuse the branch-creating git commands. This repo is trunk-based.

Wired as a PreToolUse hook on Bash in .claude/settings.json. It exists because
the prohibition was already written in .claude/skills/git-workflow/SKILL.md and
was ignored anyway: the generic "branch before committing to a default branch"
habit is stronger than a paragraph.

Deleting a branch and removing a worktree stay allowed — they are the recovery
procedure, not the mistake.
"""

import json
import re
import shlex
import sys

REASON = (
    "Blocked: this repository is trunk-based. Commit straight to `main` — "
    "`main` IS the working branch, so the usual 'protect the default branch, "
    "branch first' reflex does not apply here. If parallel edits to the same "
    "files are the worry, split the change into small commits behind a flag "
    "instead of isolating it. See .claude/skills/git-workflow/SKILL.md. "
    "(Deleting branches and removing worktrees is not blocked — that is the "
    "recovery path.)"
)

# `git branch <name>` creates; every one of these makes it do something else.
NON_CREATING_BRANCH_FLAGS = {
    "-d", "-D", "--delete", "-l", "--list", "-a", "--all", "-r", "--remotes",
    "-v", "-vv", "--verbose", "--show-current", "--merged", "--no-merged",
    "--contains", "--no-contains", "--points-at", "--format", "--sort",
    "--color", "--no-color", "-h", "--help", "--edit-description",
}


def creates_a_branch(argv: list[str]) -> bool:
    if "git" not in argv[0]:
        return False
    words = [w for w in argv[1:] if not w.startswith("-")] or [""]
    sub = words[0]

    if sub in {"checkout", "switch"}:
        return any(a in {"-b", "-B", "-c", "-C", "--create", "--force-create"} for a in argv)
    if sub == "worktree":
        return "add" in words[1:2]
    if sub == "branch":
        if any(a in NON_CREATING_BRANCH_FLAGS or a.startswith("--format=") for a in argv):
            return False
        # a bare name argument after `branch` is a creation
        return len(words) > 1
    return False


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except Exception:
        return 0

    # One Bash call may chain several commands; check each.
    for part in re.split(r"&&|\|\||[;\n|]", command):
        part = part.strip()
        if not part:
            continue
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if argv and creates_a_branch(argv):
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON,
                },
            }))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
