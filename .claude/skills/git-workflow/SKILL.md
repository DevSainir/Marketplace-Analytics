---
name: git-workflow
description: How work reaches this repository — trunk-based development (commit straight to `main`, no feature branches, no PRs for ordinary work) and which conventional-commit type to use, including the project's own `feat-minor` for features too small to deserve a minor version. Use this before committing, branching, pushing, opening a PR, or writing a commit message; whenever a session finds itself on a branch or in a git worktree; and whenever deciding whether a change is a `feat`, a `feat-minor` or a `fix`. The release machinery those types drive — Release Please, the changelog, the Telegram announcement — is documented in docs/RELEASES.md.
---

# Git workflow

## Trunk-based: commit to `main`

**Do not create branches, and do not work in an isolated worktree.** Work lands on
`main`, in small commits, pushed as it is finished. No PR is opened for ordinary work and
nothing waits for review to be merged.

`main` **is** the working branch. Committing to it is the workflow, not a hazard to be
managed — so the generic reflex "you are on the default branch, branch first to protect
it" is **wrong here**, and so is every softer version of it: no `git checkout -b`, no
`git switch -c`, no `git branch <name>`, no `git worktree add`. There is nothing to
protect `main` from; keeping work off it is the failure this repo is arranged to avoid.

**Worktree isolation is the same prohibition, and it is the one that actually bites.**
A branch under `claude/<adjective-name-hash>` in `.claude/worktrees/` is not something a
model types — it is the harness isolating a session, and it happens *before* the first
message, so no rule phrased as "do not run `git checkout -b`" can catch it. Read "no
feature branches" as covering it: do not request isolation for work in this repo, and do
not accept it silently when you are handed it. That includes spawning a subagent with
`isolation: "worktree"`, calling `EnterWorktree`, and any command that isolates by
default. Four such branches accumulated here unnoticed; one of them held a 24-file
feature that sat uncommitted for 16 days on a base that drifted 489 commits, invisible to
every later session.

**When isolation feels warranted, commit instead.** The usual trigger is parallel edits
to the same files by more than one worker. The answer is the one above: small commits,
each standing on its own, pushed as they are finished, with anything unfinished behind a
flag. That keeps other workers unblocked; a worktree only hides the work from them.

The one legitimate branch is the release bot's,
`release-please--branches--main--components--marketplace-service`. Nobody commits to it
by hand — Release Please owns it, and merging its PR cuts the release (`docs/RELEASES.md`).

### If you are on a branch anyway

Land the work first, delete second, and treat uncommitted work as the fragile case — a
worktree's working tree has no reflog behind it, so removing the worktree destroys it
outright, while a commit could still be recovered.

1. Commit whatever is uncommitted, right where you are — even as a rough checkpoint.
   This is the step that cannot be redone later.
2. From the primary checkout on `main`, land it: `git cherry-pick <sha>` (or
   `git merge --ff-only <branch>` when `main` has not moved), then run the pre-commit
   gate and push. Or push from the worktree itself, `git push origin HEAD:main`, once
   `origin/main..HEAD` holds only your commits (rebase first if `main` moved) — that
   leaves the primary checkout, where another session may have uncommitted work,
   untouched.
3. **Delete the branch the moment its work is on `main` and pushed** — in the same turn
   as the push, not at the end of the session and not as a note for the user to act on.
   A landed branch is not a backup (its commits are on `main`); it is a stale name the
   next session has to investigate before it can trust the tree. On 2026-09-28 four such
   branches and three worktrees had piled up, every one fully merged, each left behind
   by a session that pushed its work and moved on.
   * First prove nothing is lost: `git rev-list --count origin/main..<branch>` is `0`
     and `git status --porcelain` is empty.
   * The branch is usually checked out in the worktree the session runs in, so it
     cannot be deleted as is. Detach rather than remove the folder under your own feet:
     `git switch --detach`, then `git branch -D <branch>`.
   * Remove the worktree folder too (`git worktree remove <path>`) when it is not your
     session's working directory; otherwise it goes when the session closes.
   * Another session's leftover is removable on the same evidence, plus no process
     working inside it (`lsof -d cwd | grep .claude/worktrees/`).
4. Say what happened to whoever asked, including how far the branch's base had drifted.

### What trunk-based development asks in return

* **Small commits, pushed often.** A branch's job — keeping unfinished work out of
  everyone's way — now falls to commit size. If a change cannot be committed without
  breaking `main`, it is too big; split it so each commit stands on its own.
* **`main` stays green.** The pre-commit hooks (ruff, `mypy --strict`, eslint, prettier,
  the commit-message check) are the gate, and they run on every commit. Do not push past
  a failing one — there is no branch to hide the breakage on.
* **Unfinished features go behind a flag, not behind a branch.**

The single exception is a change that genuinely cannot be split and would leave `main`
broken mid-way. That is rare enough to be worth saying out loud to whoever asked, rather
than quietly opening a branch.

### The mechanical guard

Prose alone did not hold — this section already said "do not create feature branches" and
four branches appeared regardless. Two hooks in `.claude/settings.json` now back it:

* `.claude/hooks/no_branching.py` (PreToolUse on `Bash`) denies the branch-*creating* git
  commands, and any `git push` whose destination is not `main` (or the Release Please
  branch). Deleting a branch and removing a worktree stay allowed — that is the recovery
  procedure above, not the mistake.
* `.claude/hooks/trunk_check.py` (SessionStart) fires in a session that starts on any
  branch other than `main` or the Release Please branch. In the primary checkout, when the
  branch holds nothing of its own (clean tree, HEAD already on `origin/main`), it switches
  to `main` itself; otherwise it warns and points back here. This is the half that covers
  what no command-level check can see: harness worktree isolation, and Claude Code on the
  web, which checks out a `claude/...` branch before the first message and instructs the
  session to push there. That instruction does not apply in this repo — `CLAUDE.md` gives
  the standing permission to push to `main`. (On 2026-09-26 a session followed it anyway
  and pushed a feature to the side branch; the push half of the guard dates from then.)

`worktree.bgIsolation` is set to `none` in the same file so background sessions edit this
checkout directly instead of being handed a worktree.

## Which type

The version number is **derived from these types** — never typed by hand — so the choice is a
release decision, not a label. `docs/RELEASES.md` has the full table and the machinery.

| Type | Version | Use it for |
| --- | --- | --- |
| `fix:` | patch | A defect in behaviour that already shipped |
| `feat-minor:` | patch | **The default for new features.** A field, a filter, a column, a panel — anything a user would notice but nobody would announce |
| `feat:` | minor | A feature big enough to tell the team about: a new page, a new report, a new integration |
| `chore:` `docs:` `ci:` `refactor:` `test:` `style:` `build:` `perf:` | patch | Everything with no user-visible behaviour change |

**Reach for `feat-minor` first.** It exists because almost everything here is a small feature, and
a minor bump for each one made the version number say more than it meant. `feat` is the exception
you justify, not the default you fall back to. In the Telegram announcement the two are separate
headings — «Новые функции» and «Мелкие функции» — so the distinction is what the team reads.

`feat-minor` is this project's own type, not part of the Conventional Commits spec. Tools that
have not been told about it will reject it; the three places it is registered are listed in
`docs/RELEASES.md`.

A breaking change (`!` or a `BREAKING CHANGE:` footer) is still only a **minor** bump while the
version is below 1.0 — that is deliberate, so a single `!` cannot declare the project stable
before anyone decided it was.

## Writing the message

**In English.** Every commit message, subject and body — no exceptions, whatever language the
conversation that produced the change was held in. This is not a style preference, it is what the
release pipeline is built on: `.github/scripts/release_notes_ru.py` sends the commit subjects to
Gemini and asks for Russian *and* a change out of the imperative
(`add Balance table` → «была добавлена таблица Баланс»). A subject that arrives already in Russian
has nothing to translate, comes back mangled or unchanged, and when the model is unreachable the
documented fallback — "grouped English notes" — is not English either. `docs/RELEASES.md` has the
detail.

The history already holds Russian subjects. They are not the standard; they are what this rule was
written to stop, and matching them is not a reason.

The same rule covers every other piece of supporting text in the repo — comments, docstrings,
test names, TODOs. What stays Russian is what a *user* reads: UI copy, error messages sellers see,
alert text, and the documents written for the team (`docs/**`, skill files). See
`backend-architecture` and `design-system` for that boundary.

Subject in the imperative, scope = the module (`monitoring`, `finreports`, `users`, `workspaces`,
`core`, `frontend`). The body is for **why**, and it is worth writing: these messages become the
changelog and, translated, the release note the team actually reads. What the diff already shows
does not need restating.

End every commit with the `Co-Authored-By:` trailer naming the model that wrote it — the
harness supplies the exact line (`Co-Authored-By: Claude <model> <noreply@anthropic.com>`).
Copy that rather than a model name from an older commit.
