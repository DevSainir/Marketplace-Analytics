---
name: testing
description: The binding rules for every test in this repo — which tier a test belongs in (unit, component, integration, end-to-end, performance), Arrange-Act-Assert, testing behaviour instead of implementation, fakes over MagicMock, and the definition of done for a change. Use this whenever you write, move, rename, delete or debug a test, whenever you finish a code change and need to know what must be covered and where, and whenever a test fails — before re-running it, and especially for a failure that passes alone but not in its file, `got Future attached to a different loop` or `Event loop is closed`, which have a known cause here. Also use it before answering "is this already tested?" — references/coverage-map.md records what each tier owns and which gaps are deliberate.
---

# Testing rules

What is allowed to exist. `references/coverage-map.md` describes what exists today.

## The shape: a testing pyramid

Tests are organised by **speed and blast radius**, because that is what decides how often a test
can be run and how much a failure tells you. `performance/` is a separate layer alongside the
pyramid, not a level in it.

**Before writing the test, say what it pins.** One sentence on the behaviour and why it deserves
a test, agreed first — it is much cheaper to reject a tautology as a sentence than as a file.

**There is no cap on unit tests.** If a behaviour can be pinned by a fast, isolated test, pin it.

**Every end-to-end test must justify its existence.** They are the slowest, the flakiest, and the
least specific about what broke. A journey earns one only if its failure makes the product
unusable.

**Push each test as far down as it can honestly go.** A test that could pass in `unit/` but sits
in `integration/` costs the team time on every single run, forever.

| Tier | Location | May touch | Must not touch | Budget |
| --- | --- | --- | --- | --- |
| **unit** | `backend/tests/unit/`, `frontend/src/**/*.spec.js` | Pure functions, in-memory objects | Network, disk, DB, clock, Redis | < 50 ms/test |
| **component** | `backend/tests/component/` | The real app, routers, DI graph, services | Postgres, Redis, Celery, WB | < 200 ms/test |
| **integration** | `backend/tests/integration/`, `frontend/tests/integration/` | Real Postgres, real Redis, real HTTP transport | Real WildBerries, real browser | < 2 s/test |
| **end-to-end** | `tests/end-to-end/` | Everything: browser, SPA, API, DB | Production | < 60 s/test |
| **performance** | `tests/performance/` | Everything, deliberately overloaded | Production, the dev database | Unbounded |

Backend layout is `backend/tests/<tier>/<module>/`, so "run everything fast" and "run everything
for `monitoring`" are both one command. Frontend unit specs are colocated instead
(`store.js` → `store.spec.js`). **What each tier owns in detail, and why the layout is what it
is, is in `references/tier-contracts.md` — read it when deciding where a test goes.**

## Rules for every test

### Arrange–Act–Assert, separated by blank lines

Three blocks, in order, with nothing interleaved.

```python
async def test_disabled_account_cannot_rotate() -> None:
    """Disabling an account ends its sessions at the next refresh."""
    user = make_user(email="user@example.com")
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email=user.email, password=KNOWN_PASSWORD)
    user.is_active = False

    with pytest.raises(AuthenticationError, match="disabled"):
        await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)
```

If a test needs a second Act, it is two tests.

### Test behaviour, not implementation

**A refactor that preserves the output must keep every test green.** If renaming a private method
or reordering a query breaks a test, the test was pinning the implementation and is a liability.

Assert on the value returned, the status code, the row persisted, the error raised. Never on how
many times a private helper was called.

```python
# NO — pins the implementation
assert service._compute_ratio.call_count == 2

# YES — pins the behaviour
assert result.cost_ratio == Decimal("278") / Decimal("158")
```

### DAMP, not DRY

Descriptive And Meaningful Phrases. A test is read far more often than it is changed, usually by
someone debugging at speed. Repeating three lines of setup in five tests is **correct** when it
keeps each one readable end to end.

Share builders (`make_user`), canned payloads and fixtures. Do not share the assertions, or a
loop that hides which case is failing. The limit: if changing one product behaviour forces edits
in twenty places, the duplication has stopped paying for itself — extract a builder, not a base
class.

### The docstring says *why*

Every test carries a one-line docstring stating the behaviour. Where the behaviour is non-obvious
or was learned from an incident, add the reason.

```python
def test_failed_logins_are_indistinguishable() -> None:
    """Unknown user and wrong password produce the identical error message.

    Any difference here — message, code, or status — turns the endpoint into an
    account-enumeration oracle.
    """
```

A reader who does not know why a test exists cannot tell a real failure from an obsolete
assertion, and will delete the wrong one.

### Fixtures over mocks; fakes over `MagicMock`

Prefer a real object. When a collaborator must be replaced, write a **hand-written fake**
(`backend/tests/support/fakes.py`) rather than a mock.

A `MagicMock` accepts any call and returns another mock, so a renamed repository method leaves
the test green while production breaks — the exact failure the test was meant to catch. A fake
raises `AttributeError`.

Mocks are acceptable only for things that cannot be faked: `asyncio.sleep`, the system clock, an
outbound network call.

### No tautologies, no coverage theatre

Do not test the framework, a getter, or a constant.

```python
# Worthless — tests Pydantic
def test_schema_has_an_email_field():
    assert "email" in UserRead.model_fields
```

Coverage is a diagnostic for finding untested branches, never a target. A test written to raise a
percentage is worse than no test: it costs maintenance and proves nothing.

### Order independence

Any test must pass alone, in any order, and in parallel. Shared state is reset by fixtures, never
by the test that happens to run first. The settings singleton is the usual trap: mutate it only
through the `settings_override` fixture, which restores the previous value.

### Name the behaviour, not the function

`test_a_foreign_workspaces_sku_is_a_404`, not `test_get_sku_detail_2`. The name is what a reader
sees in a CI failure list; it should tell them what broke without opening the file.

## Running

Every tier is one `make` target; `make` with no target lists them all with their descriptions.
Note that the Makefile drives pytest through `uv`, which is not on a non-interactive shell's
PATH — call the venv directly there:

```bash
cd backend && .venv/bin/python -m pytest -m unit
cd backend && .venv/bin/python -m pytest tests/unit/monitoring
cd backend && .venv/bin/python -m pytest -m "not integration"
```

First-time setup for the browser tier: `npm install && npm run setup:e2e`.

## Tests that stand up their own infrastructure

The end-to-end tier brings up a whole stack, and the Docker host it runs on may be serving
another one. It is fenced off by Compose: its own project name (`marketplace-e2e`), its own
ports (8080/8443), and a guard step that fails the job if either is ever lost.

**That fence only covers what goes through Compose.** A seed script that addresses a container
*by name* (`docker exec <container> …`) is outside it, and if the name it defaults to belongs to
the other stack, the seed lands there — while every Compose guard passes. That happened once,
and `tests/unit/core/test_ci_never_targets_production.py` now pins both halves of the fix.

So, before adding or editing any step of a tier that stands up infrastructure:

* **Name the target, never inherit it.** Any `docker exec`, published port, host path or
  container name in a workflow step or a script it calls is outside the fence and must be
  passed explicitly, not defaulted.
* **A default that names a real, non-test resource is a bug**, even in a script "only ever run
  in CI".
* **Make destructive scripts recognise a live stack themselves.** `backend/scripts/load_seed.sh`
  reads `ENVIRONMENT` from the *target stack's* api container and refuses `production`. Note
  where it reads it from: a checkout's `backend/.env` is a copy of `.env.example` and says
  `local` whatever container is being addressed.
* **`monitoring` and `finreports` refuse an unannounced `TRUNCATE`** (a statement-level
  trigger; opt in with `SET LOCAL app.allow_truncate = 'on'`, and every attempt lands in
  `organizations.audit_log`). A fixture path that needs to empty a table must say so; if a
  test starts failing on that error, the target is the question to check first, not the flag.

## Definition of done for a change

1. The new behaviour has a test in the **lowest tier that can prove it**.
2. The test fails without the change — verify this; a test that never failed has not been shown
   to test anything.
3. `make test-fast` is green.
4. `make test-integration` is green when the change touches SQL, transactions, Redis, Celery, or
   a migration.
5. `references/coverage-map.md` still reads true. It records what each tier *owns* and which gaps
   are deliberate, so it needs an edit when coverage changes shape, not when a file moves.
6. Land it on `main`. This repo is **trunk-based**: commit and push straight to `main` — no feature
   branches or PRs for normal work. CI reruns every tier on the push, but there is no branch to
   hide a breakage on, so steps 1–5 are what keeps `main` green.

## When a test fails

**Never delete or skip a failing test to go green.** Either the product is broken, or the test's
premise is wrong — both must be resolved deliberately, and a wrong premise is fixed by rewriting
the assertion with a comment saying why, not by deleting the case.

A `@pytest.mark.skip` needs a reason and a linked issue. An unexplained skip is a deleted test
that still costs a line in the report.

### "attached to a different loop" always means the same thing

If an integration test fails with `Task … got Future attached to a different loop` or
`Event loop is closed`, and it passes when run alone, the cause is almost never the test
that failed. Some code it exercises reached the **process-wide** Redis client in
`src.core.redis` while an earlier test in the same file bound that client's pooled
connections to its own, now-closed, event loop.

**Fix:** declare the `redis_client` fixture on the test (or an autouse fixture in the
file). It swaps the shared client for a per-test one on the test index — which is what the
component tier's `redis_store` does for its own tier.

**Why it keeps happening:** the fixture is opt-in, so a test only has it if somebody
realised the path touched Redis. Adding a Redis-backed control to an existing code path —
the login backoff was the last one — silently pulls files into needing it that did not
before, and the failure surfaces several confusing minutes from its cause. When you put
Redis behind something that was not behind it, grep for the tests that exercise it before
assuming the fast tier's green is the whole answer.
