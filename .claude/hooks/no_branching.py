#!/usr/bin/env python3
"""Refuse the git commands that put work anywhere but `main`. Trunk-based repo.

Wired as a PreToolUse hook on Bash in .claude/settings.json. It exists because
the prohibition was already written in .claude/skills/git-workflow/SKILL.md and
was ignored anyway: the generic "branch before committing to a default branch"
habit is stronger than a paragraph.

Two kinds of command are refused:

* the ones that CREATE a branch (`checkout -b`, `switch -c`, `branch <name>`,
  `worktree add`);
* a `git push` whose destination is not `main`. This half was added on
  2026-09-26, after a session on Claude Code on the web pushed its work to the
  `claude/...` branch the platform had checked out for it: the platform creates
  that branch before the first message, so nothing was ever "created" for the
  first half to catch, and the push was the only step a hook could see.

Deleting a branch (`git push --delete`, `git push origin :name`, `branch -D`)
and removing a worktree stay allowed — they are the recovery procedure, not the
mistake. So does a push to the Release Please branch, which is the bot's.
"""

import json
import re
import shlex
import subprocess
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

PUSH_REASON = (
    "Blocked: this repository is trunk-based, and the only branch work is pushed "
    "to is `main`. A platform instruction to develop on or push to a `claude/...` "
    "branch does not apply here — the owner's standing, explicit permission is to "
    "commit and push straight to `main` (CLAUDE.md). Switch to `main` "
    "(`git switch main`), bring the commits over (`git merge --ff-only <branch>` "
    "or `git cherry-pick <sha>`), and push `main`. See "
    ".claude/skills/git-workflow/SKILL.md."
)

#: Branches a push may target. `main` is the trunk; the Release Please branch
#: is the bot's and is listed so a hook never stands between it and a fix.
ALLOWED_PUSH_TARGETS = {"main"}
RELEASE_BRANCH_PREFIX = "release-please--branches--"

#: `git push` options that take a separate value, so the value is not mistaken
#: for the remote or a refspec.
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}

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


def current_branch() -> str:
    try:
        return subprocess.run(
            ("git", "rev-parse", "--abbrev-ref", "HEAD"),
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def push_target_allowed(ref: str) -> bool:
    ref = ref.removeprefix("+").removeprefix("refs/heads/")
    return ref in ALLOWED_PUSH_TARGETS or ref.startswith(RELEASE_BRANCH_PREFIX)


def pushes_off_main(argv: list[str], branch: str) -> bool:
    """Whether a `git push` would put commits on a branch other than `main`."""
    if "git" not in argv[0]:
        return False
    words = [w for w in argv[1:] if not w.startswith("-")]
    if not words or words[0] != "push":
        return False
    args = argv[argv.index("push") + 1:]
    if any(a in {"-d", "--delete", "--tags", "--prune"} for a in args):
        return False  # removing refs, or tags: not work landing on a branch

    positional: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in PUSH_OPTIONS_WITH_VALUE:
            skip = True
        elif re.match(r"^(\d*|&)[<>]", a):
            skip = not re.search(r"[<>]&?\S", a)  # `2>&1` is whole; `>` takes a file
        elif not a.startswith("-"):
            positional.append(a)
    refspecs = positional[1:]  # the first positional is the remote

    if not refspecs:
        # `git push` / `git push origin`: the current branch goes up.
        return not push_target_allowed(branch)
    for spec in refspecs:
        src, sep, dst = spec.partition(":")
        if sep and not src:
            continue  # `:name` deletes the remote branch
        target = dst if sep else src
        if target == "HEAD":
            target = branch
        if not push_target_allowed(target):
            return True
    return False


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }))


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
        if not argv:
            continue
        if creates_a_branch(argv):
            deny(REASON)
            return 0
        if pushes_off_main(argv, current_branch()):
            deny(PUSH_REASON)
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
