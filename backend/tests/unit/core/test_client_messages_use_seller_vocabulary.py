"""Every message a user can read speaks the seller's language, not ours.

The API hands 4xx messages to the SPA, and `extractErrorMessage` puts them in
front of a seller verbatim. So a message written while reading the code —
"workspace_id is required", "the HttpOnly cookie is missing" — reaches a
person who can do nothing with it. Several had reached real screens before
this test existed.

**What is checked and what is not.** Only the exceptions whose text actually
reaches a client: `AppError` subclasses that map to a 4xx, and `HTTPException`
details. Deliberately excluded:

* :class:`IntegrationError` and anything else mapping to 5xx — the handler
  replaces those with `client_message` and the real text goes to the log, where
  developer vocabulary is correct because operators read it.
* `ValueError` raised outside a pydantic validator, which never leaves the
  process.

That the messages are English at all is the repository-wide rule in
`test_the_repository_is_in_english.py`; this file is about which English.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[3] / "src"

#: Exception types whose message is handed to the client verbatim on a 4xx.
#: `IntegrationError` is absent on purpose — see the module docstring.
CLIENT_FACING = frozenset(
    {
        "ValidationError",
        "ConflictError",
        "NotFoundError",
        "PermissionDeniedError",
        "RateLimitError",
        "AuthenticationError",
        "TokenReuseError",
        "HTTPException",
    }
)

def _literal_text(node: ast.AST) -> str:
    """The fixed text of a string node, with any interpolation dropped.

    An f-string's `{cap}` says nothing about the language it is embedded in, so
    only the literal halves are examined. Parsed rather than pattern-matched
    because a regex over `detail=` also catches `report_degraded(detail=...)`,
    which is an operator log and correctly English.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def _messages() -> list[tuple[pathlib.Path, str]]:
    """Collect every message literal raised at a client from ``src/``."""
    found: list[tuple[pathlib.Path, str]] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in CLIENT_FACING:
                continue
            parts = [_literal_text(arg) for arg in node.exc.args]
            parts += [_literal_text(kw.value) for kw in node.exc.keywords if kw.arg == "detail"]
            for text in parts:
                if text.strip():
                    found.append((path.relative_to(SRC), text))
    return found


def test_the_scan_actually_finds_messages() -> None:
    """Guard the guard.

    A regex that silently stops matching would turn this whole module into a
    test that passes because it checks nothing.
    """
    # Arrange / Act
    messages = _messages()

    # Assert — the exact number moves with the code; the order of magnitude
    # does not, and zero means the scan broke.
    assert len(messages) > 20


@pytest.mark.parametrize(
    "jargon",
    [
        "HttpOnly",
        "cookie",
        "endpoint",
        "workspace_id",
        # One word for one thing. What a seller switches between is a
        # "workspace". "Cabinet" is the calque of the word the Russian-language
        # marketplace uses for a seller's account, and a naming rule nobody can
        # fail is a naming rule that drifts back. The SPA half of the same rule
        # lives in `frontend/tests/integration/naming.spec.js`.
        "cabinet",
        "Cabinet",
    ],
)
def test_no_message_leaks_developer_vocabulary(jargon: str) -> None:
    """A message is written in the words a seller uses.

    A cookie's HttpOnly flag is not something a person can act on, and a field
    name is not a sentence. Both had reached real screens.
    """
    # Arrange / Act
    offenders = [f"{path}: {message}" for path, message in _messages() if jargon in message]

    # Assert
    assert offenders == [], f"{jargon!r} is not user vocabulary:\n" + "\n".join(offenders)
