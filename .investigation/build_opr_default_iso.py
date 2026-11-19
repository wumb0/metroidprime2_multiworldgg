"""Build an OPR-patched ISO with standalone-default settings (vanilla layout).

Applies exactly the open_prime_rando patch layer (DOL patches, tweaks, cleanup,
custom models) with RandoConfiguration defaults — no randomizer logic runs, the
world layout stays vanilla. Intended for the morph-ball/Dark-Visor hang A/B
test: if this ISO hangs on the repro, the bug is in the OPR patch layer, not in
MultiWorldGG content.

Setup (any OS, using uv):
    uv venv .venv
    uv pip install --python .venv open-prime-rando

Build:
    Windows:  .venv\Scripts\python build_opr_default_iso.py echoes.iso echoes-opr-default.iso
    POSIX:    .venv/bin/python     build_opr_default_iso.py echoes.iso echoes-opr-default.iso

Then: boot the output in Dolphin, cheat/practice yourself Dark Visor + Morph
Ball, and attempt the hang repro (un-morph, immediately spam to Dark Visor).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from open_prime_rando.echoes.patcher import patch_iso
from open_prime_rando.echoes.rando_configuration import RandoConfiguration


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input-echoes.iso> <output.iso>", file=sys.stderr)
        return 1
    input_iso = Path(sys.argv[1])
    output_iso = Path(sys.argv[2])
    if not input_iso.is_file():
        print(f"input not found: {input_iso}", file=sys.stderr)
        return 1

    # Every field default = what the standalone OPR GUI ships with; the three
    # required fields only affect the name/title text/seed, nothing patching.
    configuration = RandoConfiguration(
        game_title="Echoes OPR Default",
        title_screen_text="OPR DEFAULT TEST",
        seed=12345,
    )

    def status(text: str, percent: float) -> None:
        print(f"[{percent * 100:5.1f}%] {text}", flush=True)

    patch_iso(
        input_iso,
        output_iso,
        configuration,
        area_status_update=status,
        build_files_status_update=status,
        build_paks_status_update=status,
        nod_status_update=status,
    )
    print(f"OK: wrote {output_iso} ({output_iso.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
