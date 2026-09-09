# Versioning and releases

The project is versioned with [Semantic Versioning](https://semver.org), starting at **0.1.0**.
Nobody types a version number: it is derived from the Conventional Commits already enforced at
commit time by the `commitizen` hook in `.pre-commit-config.yaml`.

## How a release happens

1. You push conventional commits to `main` as usual (this repo is trunk-based).
2. `.github/workflows/release.yml` runs [Release Please](https://github.com/googleapis/release-please),
   which opens a pull request titled `chore(release): vX.Y.Z` describing the version it would
   produce and the changelog it would write — and then **merges it automatically**.
3. That merge **is** the release. Release Please then:
   * writes `CHANGELOG.md`,
   * bumps `version.txt`, `backend/pyproject.toml` and `frontend/package.json` to the same number,
   * tags `vX.Y.Z` and publishes a GitHub Release.
4. The merge lands on `main` like any other commit, so `tests` runs and the VPS auto-deploys on green.
5. The release announcement to Telegram is **off** (see below) — nothing is sent on a version bump.

### Holding a release

Every push to `main` therefore releases. To stop one, label the open PR **`hold-release`**: the
merge step skips it and the PR stays open until you remove the label (the next push re-runs the
workflow and merges it then). Leaving it open is no longer enough on its own.

The merge is deliberately not gated on the PR's own checks — they never run. GitHub holds workflow
runs for Actions-opened PRs at `action_required`, so waiting for green there would wait forever.
The gate is the merge commit on `main`, which runs the full pipeline before anything deploys.
(`tests` no longer runs on `pull_request`, so the release PR now carries no checks at all — see
[Known wrinkle](#known-wrinkle) for what that replaced.)

### Which number you get

| Commit | Effect while < 1.0 |
| --- | --- |
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat-minor:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | minor — `0.1.0` → `0.2.0` |
| `chore:`, `docs:`, `ci:`, … | patch, and appears in the changelog under its own section |

`feat-minor:` is ours, not part of the Conventional Commits spec, and it exists because most
features here are not worth a minor bump — see the git-workflow skill for which one to reach for.
Nothing configures it as "patch": Release Please bumps **minor only for the literal type `feat`**
and major only for a breaking change, and everything else falls through to patch. So the type
needed no bump rule, only three registrations, and the failure mode if you add another such type
and forget one of them is silence rather than an error:

* `release-please-config.json` → a `changelog-sections` entry, or it is absent from the changelog
  (an explicit sections list hides every type it does not name);
* `.cz.toml` → the `schema_pattern`, or the commit-msg hook rejects the commit outright — the one
  registration that fails loudly;
* `.github/scripts/release_notes_ru.py` → `SECTIONS`, or the Telegram announcement files it under
  «Прочее». Its `CONVENTIONAL` regex also has to allow the hyphen.

The last row of that table is the reason for `"bump-minor-pre-major": true` in
`release-please-config.json`: without it a single `!` commit would declare the project 1.0.0 long
before anyone decided it was. Delete that line when the API is actually stable, and the normal
SemVer rules take over.

To force a specific number once, put `Release-As: 1.0.0` in a commit body.

### Why `separate-pull-requests` is true for a single package

It reads like a contradiction and is not. There is one package, so it changes nothing about how
many PRs get opened — what it does is keep the **Merge plugin** out of the way. With it `false`,
Merge runs even for a single package, discards `pull-request-title-pattern`, and hardcodes
`chore: release main`. That title then lands on `main` as a commit subject, where the release
announcement has to recognise and drop it. `release_notes_ru.py` filters the whole family of
release-bot subjects anyway — belt and braces — but the PR is easier to read when its title says
which version it releases.

## Where the version lives

`version.txt` at the repo root is the source of truth; `backend/pyproject.toml` and
`frontend/package.json` are kept in step by Release Please and should never be edited by hand.
The `# x-release-please-version` comment in `pyproject.toml` is what marks the line to update —
do not remove it.

There is a fifth file nobody thinks of: **`backend/uv.lock` records the project's own version**,
not just its dependencies. A version bump therefore leaves the committed lock one line stale, and
`uv sync --locked` fails — which takes out `lint + types + fast tiers` and, through
them, the deploy gate. v0.1.1 was tagged and released and production never saw it, for exactly
that one line.

The release workflow now runs `uv lock` on the release branch and commits the result, so the
commit that lands on `main` is self-consistent. `--locked` stays: it is what stops CI installing a
dependency set the lock does not describe, and the right response to a stale lock is to update it,
not to stop checking. If you ever bump a version by hand, run `uv lock` in the same commit.

The `v0.1.0` tag is the baseline: the state of the project when versioning was introduced.
Everything before it predates the changelog. It exists so that Release Please and the
announcement both have something to diff the first release against — without it, the first
changelog would be the entire history of the repository.

## Notifications

All of it goes through `.github/scripts/telegram_notify.py`, which exists so that one rule cannot
be forgotten: **every message is sent silently** (`disable_notification`). Deploys are unattended
and backups run at 03:00; the requirement is that the message is waiting in the morning, not that
it wakes anyone. There is deliberately no flag to turn this off, and
`backend/tests/unit/core/test_release_notifications.py` fails if someone adds one.

| What | Audience | Language | State |
| --- | --- | --- | --- |
| Deploy succeeded / failed | `TELEGRAM_MAIN_CHAT_ID` | English | **on** |
| Backup failed (VPS cron) | `BACKUP_ALERT_TELEGRAM_CHAT_ID` in the server `.env` | English | **on** |
| Release published | `TELEGRAM_MAIN_CHAT_ID` + `WORKERS_TELEGRAM_CHAT_IDS` | Russian | **off** |

Operational news is for whoever fixes it. Release news is for whoever uses the product — which is
why it is translated.

### The release announcement is currently off

Every push to `main` cuts a release, so the announcement fired on every version bump — including
the `fix:` and `chore:` ones nobody wants a Telegram message about. The three steps that build and
send it are gated on a repository variable and stay dormant until it exists:

```
if: steps.release.outputs.release_created && vars.ANNOUNCE_RELEASES == 'true'
```

To turn it back on, add repository variable **`ANNOUNCE_RELEASES` = `true`** (Settings → Secrets
and variables → Actions → Variables). Nothing else changes: the translation pipeline, the audience
split and the secrets are all still wired, and `release_notes_ru.py` is still covered by its tests,
so re-enabling is one variable rather than a revert.

Deploy and backup alerts are untouched by this and keep firing.

### The translation

`.github/scripts/release_notes_ru.py` sends the release's commit subjects to Gemini and asks for
two things: Russian, and a change of verb form out of the imperative.

```
feat(finreports): add Balance table
→ • Модуль финотчётов: была добавлена таблица Баланс.
```

The first is obvious; the second is the part that makes the note readable. `add Balance table` is
written for the person who wrote the code. «была добавлена таблица Баланс» is written for the
person who now has the table.

Three details that are not decoration:

* **The scope glossary is in the prompt.** `finreports` becomes «модуль финотчётов» in every
  release, instead of drifting between three plausible translations.
* **Telegram's HTML is not HTML.** It has `<b>`, `<i>`, `<code>` and `<a>`, and no `<ul>`/`<li>` —
  a list the model emits anyway is a 400 and a lost announcement. `telegram_notify.py` degrades
  list markup to bullets and escapes anything else before sending, and falls back to plain text
  if Telegram rejects the message regardless.
* **The model is discovered, not hardcoded.** The script asks the API which models this key may
  use for `generateContent`, ranks them (flash before pro, released before preview, newest
  version first, `-latest` aliases last because they move between releases) and tries the top
  three. A hardcoded name is a slow-motion outage — see below.

The message carries only the version: no repository name, no GitHub link. The repo is private,
so both are noise to every recipient who cannot open them.

If Gemini is unreachable or the key is missing, the announcement still goes out, in grouped
English, with a note saying the translation was unavailable. A release nobody hears about is a
worse failure than one announced in the wrong language.

`GEMINI_MODEL` (a repository **variable**) is prepended to the discovered list if you need to pin
one; a stale value degrades to "tried first" rather than disabling translation.

## When the announcement arrives in English

That is the fallback working, not the pipeline breaking — but the reason is always in the
`Announce the release in Telegram` step's log, which names the model and quotes the API's own
explanation. The v0.1.1 release is the worked example: `gemini-2.5-flash` answered **404** (not
available for that key's API version) and `gemini-2.0-flash` was rate limited six times in a row.
Model discovery exists because of that release.

Both scripts print the API's own error text now. That is safe and deliberate: the Gemini key
travels in the `x-goog-api-key` **header** and is scrubbed from any logged text anyway, and the
bot token is in the Telegram **URL**, never in a response body.

## When a recipient does not get the message

The step ends with `Delivered to N/M chat(s)`. A chat that fails with **`Bad Request: chat not
found`** has not gone wrong in this repo: a Telegram bot cannot open a conversation, so each
person in `WORKERS_TELEGRAM_CHAT_IDS` must send the bot `/start` once (or the bot must be a
member of the group). Until they do, their id is unreachable no matter what is deployed.

## Secrets

| Name | Used by |
| --- | --- |
| `GEMINI_API_KEY` | release announcement translation |
| `TELEGRAM_BOT_TOKEN` | every notification |
| `TELEGRAM_MAIN_CHAT_ID` | deploy + release notifications |
| `WORKERS_TELEGRAM_CHAT_IDS` | release notifications — comma, space or semicolon separated |

`TELEGRAM_CHAT_ID` is no longer read by anything and can be deleted.

## Known wrinkle

The release PR is opened by `GITHUB_TOKEN`, and GitHub holds workflow runs for PRs that Actions
opened at **`action_required`** until a human approves them. Nothing waits on it: the merge commit
lands on `main` where the full pipeline runs and gates the deploy.

**What this section used to claim, and why it was wrong (corrected 2026-09-07).** It said the PR
simply shows a run with an *Approve and run* button — "it has not failed, it has not started". The
second half was true and the first was not. A held run is not held indefinitely: GitHub **expires**
it as soon as something supersedes it or the PR closes, and an expired run's conclusion is
`failure`. This workflow causes both, within seconds — release-please pushes twice (the bump, then
the `uv.lock` sync), and then the merge step closes the PR. So every release left two red ✗ on
`tests`, each one twelve seconds long, with **zero jobs executed** and the banner:

> This run likely failed because of a workflow file issue.

That banner is misleading — it sends you to the YAML, which is fine and passes on `main` minutes
later. The annotation below it is the true one:

> This workflow run required approval but was not approved before it expired.

Nothing was ever broken by this: `deploy` reads the `main` run, so releases shipped normally. The
cost was that every release trained people to read a red check as noise.

**The fix**: `tests` no longer triggers on `pull_request` at all. In a trunk-based repository the
release PR is the only PR there is, its contents reach `main` in the merge commit seconds later,
and they are tested there in full before anything deploys. The head branch could not be filtered
out instead — `pull_request.branches` matches the *base* branch, and the approval is held at run
level, so no job-level `if:` is ever reached. To run the pipeline against a branch by hand,
dispatch `tests` at it; that also offers `run_slow_tiers`, which a PR run never did.
`backend/tests/unit/core/test_no_workflow_runs_on_pull_request.py` fails if the trigger comes back.

The same rule has a sharper edge on the automatic merge, and it is the reason that step does more
than call `gh pr merge`. **A merge performed with `GITHUB_TOKEN` pushes to `main` without
triggering any workflow** — the property the `uv.lock` push relies on to avoid looping. Two things
a human merge would have started go missing with it:

* `tests`, whose green run is what `deploy` waits for. Without it the bump sits on `main`,
  released and never shipped — v0.1.1's failure reached from the other direction.
* `release` itself, which is what sees the merged PR and creates the tag, the GitHub Release and
  the announcement. Without it the PR merges and no release is ever cut.

`workflow_dispatch` is the documented exception, so the merge step starts both explicitly. A
dispatched `tests` on `main` runs the same tiers a push does — `end-to-end` keys off the branch and
`performance` is opt-in either way — so the deploy gate keeps its full strength.

### «Base branch was modified» on the automatic merge

Seen once on 2026-08-17 (v0.7.6): the merge step failed with
`GraphQL: Base branch was modified. Review and try the merge again.`, the release PR stayed open,
and `main` kept the previous version numbers — while the deploy of that same commit succeeded, so
the code was live and only the bump was missing.

It is a **race, not a conflict**. The step above it pushes `uv.lock` to the release branch, and a
merge issued while GitHub is still recomputing the PR's mergeability is refused with that message.
The step now retries five times with a growing pause and treats "already merged" (a concurrent run
won) as success. If all five are refused it fails loudly rather than skipping quietly, because the
deploy has already happened by then; the next push re-runs the workflow and merges the PR.

The suppression reaches one level further than it looks, and v0.5.2 paid for the lesson: it was
tagged and announced and never shipped, because the **`workflow_run` event `tests` emits to start
`deploy` is suppressed too** when the run itself was dispatched by `GITHUB_TOKEN`. So `tests` hands
off to `deploy` explicitly for dispatched runs on `main` (`deploy-after-dispatch` in `tests.yml`),
and only for those — a normal push still arrives through `workflow_run`, and dispatching there as
well would deploy the same commit twice.

If you ever move the merge onto a PAT, delete all three hand-offs: with a real user token the push
triggers everything by itself, and each would fire twice.
