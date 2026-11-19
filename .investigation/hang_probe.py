"""Snapshot Echoes morph/visor/HUD state from a live Dolphin via the memory engine.

Usage (game running, Dolphin API enabled):
    .venv/bin/python .investigation/hang_probe.py [label]

Run it: once standing normally, once in Morph Ball, and 2-3 times ~1s apart
*while hung*, with different labels. Diffing the snapshots shows which flag is
wedged. NTSC-U addresses; see versions.py for PAL variants.

Address sources (see FINDINGS-morph-hud.md):
- cstate_manager_global 0x803DB6E0 (versions.py), CPlayer at +0x14FC,
  CPlayerState at +0x150C (versions.py).
- CPlayer: +0x38c morph mode (SetMorphMode 0x80016a14), +0x390 submode,
  +0x169 in-ball bool.
- CPlayerState: +0x30 current visor, +0x34 transitioning-to visor, +0x50 float.
- HUDController singleton pointer at 0x803B1F30 (global read by
  DisplayTemporaryHudMessage at 0x8006B3C8: lis -0x7fc5 / addi 0x1f30);
  +0x6b4/+0x788/+0x7f4/+0x800 are frame-ish pointer candidates from the HUD
  Update function — raw-dumped, semantics TBD from the diff.
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

import dolphin_memory_engine as dme

CSTATE = 0x803DB6E0
CPLAYER_OFF = 0x14FC
STATE_OFF = 0x150C
MORPH_MODE = 0x38C
MORPH_SUBMODE = 0x390
MORPH_FLAG = 0x169
VISOR_CURRENT = 0x30
VISOR_TRANSITIONING = 0x34
VISOR_FLOAT = 0x50
HUD_SINGLETON_PTR = 0x803B1F30
VISOR_NAMES = {0: "Combat", 1: "Dark", 2: "Echo", 3: "Scan"}


def u32(addr: int) -> int:
    return dme.read_word(addr)


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "snap"
    if not dme.is_hooked():
        dme.hook()
        time.sleep(0.3)
    if not dme.is_hooked():
        print("not connected to Dolphin (API enabled? game running?)", file=sys.stderr)
        return 1

    cstate = u32(CSTATE)
    if not 0x80000000 <= cstate < 0x81800000:
        print(f"cstate manager global not populated: {cstate:#x}")
        return 1
    player = u32(cstate + CPLAYER_OFF)
    state = u32(cstate + STATE_OFF)
    hud = u32(HUD_SINGLETON_PTR)

    lines = [f"=== {label} @ {time.strftime('%H:%M:%S')} ==="]
    lines.append(f"cstate={cstate:#010x} player={player:#010x} state={state:#010x} hud={hud:#010x}")
    if 0x80000000 <= player < 0x81800000:
        morph = u32(player + MORPH_MODE)
        ball = u32(player + MORPH_FLAG) & 0xFF
        lines.append(
            f"morph_mode={morph} ({['standing', 'toBall', 'ball?', 'fromBall'][morph] if morph < 4 else '?'}) "
            f"submode={u32(player + MORPH_SUBMODE)} in_ball_flag={ball}"
        )
    if 0x80000000 <= state < 0x81800000:
        cur = u32(state + VISOR_CURRENT)
        pend = u32(state + VISOR_TRANSITIONING)
        f = dme.read_float(state + VISOR_FLOAT)
        lines.append(
            f"visor current={cur} ({VISOR_NAMES.get(cur, '?')}) pending={pend} "
            f"({VISOR_NAMES.get(pend, '?')}) float={f:.4f}"
        )
    if 0x80000000 <= hud < 0x81800000:
        for field in (0x6B4, 0x788, 0x7F4, 0x800):
            lines.append(f"hud+{field:#x} = {u32(hud + field):#010x}")
        raw = dme.read_bytes(hud, 0x60)
        words = struct.unpack(">24I", raw)
        lines.append("hud[0x00:0x60] = " + " ".join(f"{w:08x}" for w in words))
    else:
        lines.append("HUDController singleton null (in a cutscene/loading?)")

    text = "\n".join(lines)
    print(text)
    out = Path(__file__).with_name("hang_snapshots.txt")
    with open(out, "a") as f:
        f.write(text + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
