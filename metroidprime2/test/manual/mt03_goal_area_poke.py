"""MT03 -- goal *detection* alone, by poking the current-area memory field.

Goal detection (``client/client.py::_handle_check_goal``) is a memory read:
the current MLVL must be Temple Grounds and the current area's TAreaId
(``EchoesInterface.current_area_id``, at
``cstate_manager_global + versions.AREA_ID_OFFSET``) must be one of
``constants.GAME_END_AREA_INDICES``. This test fakes the latter without
having to kill the final boss, mirroring how ``worlds/metroidprime``'s
client reads the current level straight from memory.
"""

from __future__ import annotations

from ... import constants
from ...client import versions
from . import harness, presets
from .harness import ManualTest, Step

_CREDITS_AREA_INDEX = 53  # !!game_end_part3, Temple Grounds' Credits room
assert _CREDITS_AREA_INDEX in constants.GAME_END_AREA_INDICES


def _pointer_chain(version: versions.EchoesVersionInfo) -> str:
    return (
        f"{version.name}: the current area's TAreaId lives at "
        f"`0x{version.cstate_manager_global:08X} + 0x{versions.AREA_ID_OFFSET:X}` "
        f"(write a u32 `{_CREDITS_AREA_INDEX}`, a member of "
        f"`constants.GAME_END_AREA_INDICES`)."
    )


TEST = ManualTest(
    slug="mt03_goal_area_poke",
    title="Goal: detection fires off a live memory read",
    priority="P0",
    proves="the goal *detector* fires off a real memory read on this build, without the final boss",
    seed=1_000_003,
    config_sha256="5b04b0c531835f9c1bb16cc57caf4712f52c28edd522d471ccf9185d8e88c620",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS),
    notes=[_pointer_chain(versions.NTSC), _pointer_chain(versions.PAL)],
    steps=[
        Step(
            "Build (any seed works) and start any game in a Temple Grounds room (e.g. Landing Site).",
            "You are in-game with the client connected; the current MLVL is Temple Grounds.",
        ),
        Step(
            "Open Dolphin's Memory viewer and follow the address above for your ISO version.",
            "You find the live current-area TAreaId field.",
        ),
        Step(
            f"Write `{_CREDITS_AREA_INDEX}` to that field.",
            "Within one client tick the client logs the goal and sends StatusUpdate(GOAL); the "
            "server marks the slot finished.",
        ),
    ],
    pass_criteria=[
        "The goal is reported exactly once.",
        "No spurious location checks are sent.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/client.py::_handle_check_goal`",
        "`constants.GAME_END_AREA_INDICES`",
        "`client/versions.py` AREA_ID_OFFSET for this build",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
