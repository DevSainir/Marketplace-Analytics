# Frontend integration tests

Unit specs live **next to the code they test** (`store.js` → `store.spec.js`).
That is the project's convention and it does not change.

This folder is for the tests that have no single owner — flows that only exist
when several units are wired together:

| Spec                        | Units it spans                                      |
| --------------------------- | --------------------------------------------------- |
| `auth-session-flow.spec.js` | axios interceptors + auth api + auth store          |
| `workspace-context.spec.js` | axios header state + workspace store + localStorage |
| `router-guard.spec.js`      | real vue-router + auth guard + auth store           |

**When to add here instead of beside the source**

Put a spec here only if it would be dishonest to place it next to one file —
i.e. it would fail for a reason that file does not own. If a test can name a
single owning module, it belongs beside that module.

HTTP is mocked at the axios adapter (`axios-mock-adapter`); everything above it
is the real implementation. Nothing here starts a browser or a backend — that is
the end-to-end tier, in `tests/end-to-end/` at the repository root.
