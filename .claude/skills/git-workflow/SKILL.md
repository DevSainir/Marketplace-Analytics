---
name: git-workflow
description: How work reaches this repository — trunk-based development (commit straight to `main`, no feature branches, no PRs for ordinary work) and which conventional-commit type to use, including the project's own `feat-minor` for features too small to deserve a minor version. Use this before committing, branching, pushing, opening a PR, or writing a commit message, and whenever deciding whether a change is a `feat`, a `feat-minor` or a `fix`. The release machinery those types drive — Release Please, the changelog, the Telegram announcement — is documented in docs/RELEASES.md.
---

# Git workflow

## Trunk-based: commit to `main`

**Do not create feature branches.** Work lands on `main`, in small commits, pushed as it is
finished. No PR is opened for ordinary work and nothing waits for review to be merged.

That means the usual "branch first if you are on the default branch" reflex is **wrong here** —
`main` is the working branch. If you find yourself on a branch, it is either the release bot's
(`release-please--branches--main--...`, which nobody commits to by hand) or a leftover; land the
work on `main` and delete it.

What trunk-based development asks in return, and what actually matters day to day:

* **Small commits, pushed often.** A branch's job — keeping unfinished work out of everyone's
  way — now falls to commit size. If a change cannot be committed without breaking `main`, it is
  too big; split it so each commit stands on its own.
* **`main` stays green.** The pre-commit hooks (ruff, `mypy --strict`, eslint, prettier, the
  commit-message check) are the gate, and they run on every commit. Do not push past a failing
  one — there is no branch to hide the breakage on.
* **Unfinished features go behind a flag, not behind a branch.**

The single exception is a change that genuinely cannot be split and would leave `main` broken
mid-way. That is rare enough to be worth saying out loud to whoever asked, rather than quietly
opening a branch.

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

Subject in the imperative, scope = the module (`monitoring`, `finreports`, `users`, `workspaces`,
`core`, `frontend`). The body is for **why**, and it is worth writing: these messages become the
changelog and, translated, the release note the team actually reads. What the diff already shows
does not need restating.

End every commit with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```
