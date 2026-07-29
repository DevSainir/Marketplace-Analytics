"""Architecture tests: the rules in the ``backend-architecture`` skill
(``.claude/skills/backend-architecture/SKILL.md``).

These rules were written down and then enforced by review alone. The frontend
already has a machine gate for the same ideas (``frontend/eslint.config.js``
makes a horizontal import a fatal lint error); the backend had none, so nothing
but attention stopped ``src/modules/a/services.py`` from importing
``src/modules/b/repos.py`` and quietly welding two domains together.

Four properties are pinned here, all read straight from the source tree with
``ast`` — no imports are executed, so a test failure names the offending file
instead of blowing up at collection:

1. **No horizontal imports.** Cross-module traffic goes through ``contract.py``.
2. **Every module publishes a contract**, so there is always a legal way in.
3. **Contracts do not rot.** Every name a contract advertises must actually
   resolve — this is what makes a currently-unconsumed contract (``monitoring``,
   ``finreports``) a maintained surface rather than dead code.
4. **The 500-line hard limit** on any single source file.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

#: Repository-relative root of the backend source tree.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_SRC = _BACKEND_ROOT / "src"
_MODULES = _SRC / "modules"

#: No Python source file may exceed this. 300 is the "start looking
#: for a split" mark; this is the hard ceiling that fails a build.
_MAX_FILE_LINES = 500

#: Directories whose files are checked for the size limit. Migrations are
#: excluded: their length is dictated by the schema change they carry and a
#: mechanical split would make them harder, not easier, to audit.
_SIZE_CHECKED_DIRS = ("src", "scripts", "tests")


def _module_names() -> list[str]:
    """Return the business modules discovered under ``src/modules``."""
    return sorted(
        path.name
        for path in _MODULES.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    )


def _python_files(root: Path) -> list[Path]:
    """Return every non-cached ``.py`` file under a directory."""
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_modules(path: Path) -> set[str]:
    """Return the dotted ``src.modules.*`` targets a file imports.

    Args:
        path: The source file to parse.

    Returns:
        Every imported dotted name that starts with ``src.modules.``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
        elif isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
    return {name for name in targets if name.startswith("src.modules.")}


@pytest.mark.parametrize("module", _module_names())
def test_a_module_reaches_other_modules_only_through_their_contract(module: str) -> None:
    """Horizontal imports are forbidden; ``contract.py`` is the only door.

    A direct import of another module's ``services``/``repos``/``models`` binds
    two domains to each other's internals, so neither can be refactored without
    the other. The contract exists precisely so that dependency has a stable,
    intentional shape.
    """
    offenders: list[str] = []
    for path in _python_files(_MODULES / module):
        for target in _imported_modules(path):
            other = target.split(".")[2]
            if other == module:
                continue  # a module may freely import its own internals
            if target != f"src.modules.{other}.contract":
                offenders.append(f"{path.relative_to(_BACKEND_ROOT)} -> {target}")

    assert not offenders, (
        f"'{module}' reaches into another module's internals:\n  "
        + "\n  ".join(offenders)
        + "\nImport from 'src.modules.<name>.contract' instead."
    )


@pytest.mark.parametrize("module", _module_names())
def test_every_module_publishes_a_contract(module: str) -> None:
    """A module with no ``contract.py`` has no legal way for anyone to use it."""
    assert (_MODULES / module / "contract.py").is_file(), (
        f"'{module}' has no contract.py, so any future consumer would have to "
        f"break the no-horizontal-imports rule to reach it."
    )


@pytest.mark.parametrize("module", _module_names())
def test_a_contract_advertises_only_names_it_can_actually_export(module: str) -> None:
    """Every name in a contract's ``__all__`` must resolve.

    This is what keeps an as-yet-unconsumed contract honest. ``monitoring`` and
    ``finreports`` are currently leaves — nothing imports them — so without this
    check their re-exports could silently rot behind a renamed service or DTO
    and only fail years later, on the first import.
    """
    contract = importlib.import_module(f"src.modules.{module}.contract")
    exported = getattr(contract, "__all__", None)

    assert exported, f"src/modules/{module}/contract.py declares no __all__."
    missing = [name for name in exported if not hasattr(contract, name)]
    assert not missing, f"src/modules/{module}/contract.py advertises missing names: {missing}"


def test_no_source_file_exceeds_the_hard_line_limit() -> None:
    """500 lines is a ceiling, not a suggestion.

    The rule exists because the alternative is what it replaced — single files
    holding several responsibilities that nobody could review as a whole. Split
    by responsibility into a package with a facade; never mechanically by line
    count.
    """
    oversized = {
        str(path.relative_to(_BACKEND_ROOT)): len(path.read_text(encoding="utf-8").splitlines())
        for directory in _SIZE_CHECKED_DIRS
        for path in _python_files(_BACKEND_ROOT / directory)
        if len(path.read_text(encoding="utf-8").splitlines()) > _MAX_FILE_LINES
    }

    assert not oversized, (
        f"These files exceed the {_MAX_FILE_LINES}-line hard limit "
        f"(split by responsibility, not by line count): {oversized}"
    )
