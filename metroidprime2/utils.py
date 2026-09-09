"""Small utility helpers for Metroid Prime 2: Echoes: apworld version
lookup, output path derivation, and the open-prime-rando dependency
bootstrap. Mirrors ``worlds/metroidprime/PrimeUtils.py``'s
``get_apworld_version`` / ``get_output_path`` / ``setup_libs`` (PLAN.md
section I).
"""

from __future__ import annotations

import os
import pkgutil
import sys
from importlib.metadata import PackageNotFoundError, version

# Keep this in sync with requirements.txt / archipelago.json's
# minimum_ap_version story: the exact open-prime-rando release this world
# was written and tested against (PLAN.md Context table, risk L6).
OPEN_PRIME_RANDO_VERSION = "0.20.1"
_RUNTIME_REQUIREMENTS = (
    f"open-prime-rando[nod]=={OPEN_PRIME_RANDO_VERSION}",
    "dolphin-memory-engine>=1.3.0",
)


def get_apworld_version() -> str:
    """The apworld's own version string, from ``version.txt``.

    Uses ``pkgutil.get_data`` (via ``importlib.resources`` under the hood
    for zipped packages) so this also works when the world is loaded
    straight out of a built ``.apworld`` zip.
    """
    # pkgutil resolves this relative to the package, so plain "version.txt"
    # works on every platform; matching PrimeUtils.get_apworld_version's
    # Windows-vs-posix split isn't actually needed here, but the extra
    # os.path.dirname() indirection Prime 1 uses would be also be harmless
    # if it were needed on some platform in the future.
    data = pkgutil.get_data(__name__, "version.txt")
    assert data is not None, "version.txt missing from metroidprime2 package"
    return data.decode().strip()


def get_output_path(apmp2_file: str) -> str:
    """The default patched-ISO path for a given ``.apmp2`` file: same
    directory/basename, ``.iso`` extension."""
    base_name = os.path.splitext(apmp2_file)[0]
    return f"{base_name}.iso"


def _open_prime_rando_satisfied() -> bool:
    try:
        return version("open-prime-rando") == OPEN_PRIME_RANDO_VERSION
    except PackageNotFoundError:
        return False


def setup_libs() -> None:
    """Ensure ``open-prime-rando`` (and its runtime dependencies) are
    importable before the client tries to patch an ISO.

    Cheap when already satisfied (a single ``importlib.metadata.version``
    lookup). For source installs/dev checkouts -- the only supported mode
    in M2 -- installs straight into ``Utils.home_path('lib')`` with pip,
    matching ``worlds/metroidprime/PrimeUtils.setup_libs``'s non-frozen
    branch. Frozen-build wheel bootstrapping is deferred to PLAN.md M5; in
    the meantime this only logs install instructions instead of crashing
    so a frozen build without the dependency still starts up (just unable
    to patch until the user installs it manually).
    """
    import Utils

    lib_path = Utils.home_path("lib")
    if lib_path not in sys.path:
        sys.path.append(lib_path)

    if _open_prime_rando_satisfied():
        return

    if Utils.is_frozen():
        print(  # noqa: T201 -- user-facing missing-dependency message
            "Metroid Prime 2: Echoes requires "
            f"open-prime-rando=={OPEN_PRIME_RANDO_VERSION}, which is not "
            "installed. Frozen MultiWorldGG builds cannot install it "
            "automatically yet (see PLAN.md milestone M5); please run:\n"
            f"    pip install {' '.join(_RUNTIME_REQUIREMENTS)}\n"
            "using the Python environment MultiWorldGG was built with, "
            "then restart MultiWorldGG."
        )
        return

    import subprocess

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            *_RUNTIME_REQUIREMENTS,
            "--target",
            lib_path,
        ]
    )
