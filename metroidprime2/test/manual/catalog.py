"""Imports every ``mt*.py`` module in this package and exposes the ordered
list of their ``TEST`` specs. Used by ``build_readme.py`` and by
``test/test_manual_plan.py`` so the README and the suite can never drift
from the scripts.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from .harness import ManualTest

_MODULE_RE = re.compile(r"^mt\d+_.+\.py$")


def _module_names() -> list[str]:
    names: list[str] = []
    for path in sorted(Path(__file__).parent.glob("mt*.py")):
        if path.name == "__init__.py" or not _MODULE_RE.match(path.name):
            continue
        names.append(path.stem)
    return names


def load_tests() -> list[tuple[str, ManualTest]]:
    """``[(module_name, TEST), ...]`` in module-name order."""
    package = __package__ or "metroidprime2.test.manual"
    loaded: list[tuple[str, ManualTest]] = []
    for name in _module_names():
        module = importlib.import_module(f"{package}.{name}")
        test = getattr(module, "TEST", None)
        if not isinstance(test, ManualTest):
            raise TypeError(f"{name}: module-level TEST is not a ManualTest (got {test!r})")
        loaded.append((name, test))
    return loaded


TESTS: list[ManualTest] = [test for _name, test in load_tests()]


def get(slug: str) -> ManualTest:
    for test in TESTS:
        if test.slug == slug:
            return test
    raise KeyError(slug)
