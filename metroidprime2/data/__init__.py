"""Read-only access to the vendored randovania data files.

``load_json`` works both from a checked-out source tree and from inside a
built ``.apworld`` zip (``importlib.resources`` abstracts over both).
Results are cached so repeated calls (e.g. once per player in a multiworld)
only touch the filesystem/zip once per process.
"""

from __future__ import annotations

import functools
import importlib.resources
import json
from typing import Any


@functools.lru_cache(maxsize=None)
def load_json(relative: str) -> Any:
    """Load and parse a JSON file stored under this package, by relative path.

    ``relative`` uses ``/`` as a separator regardless of platform, e.g.
    ``"logic_database/header.json"``.
    """
    ref = importlib.resources.files(__package__)
    for part in relative.split("/"):
        ref = ref.joinpath(part)
    with ref.open("rb") as f:
        return json.load(f)
