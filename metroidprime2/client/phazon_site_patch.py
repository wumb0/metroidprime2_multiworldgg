"""Pre-scanned Phazon Site (``pre_scan_phazon_site``).

Dark Agon Wastes' Phazon Site hides a laser barrier behind three scan posts.
Each post's scan completes ``[OUT] Scanned Post N``, which increments the
``AdvancedCounter "Setup Scans"`` (0x460207); its three states play the
light/barrier sequences (the barrier-removal cutscene is
``SQTR "[IN] Show Laser Barrier Removal"``) and activate the
``MemoryRelay "Stay Solved 1/2/3"`` (0x460222-0x460224), which is what the
game remembers in the save. Those three relays are ``delayed_action``: during
play activating one only records it, and it is when the room is next loaded
that their ``Active`` connections fire, replaying the solved state without the
cutscene -- each increments the counter again and ``Deactivate``s that step's
cutscene relay (the third also ``Activate``s ``"[IN] Persistent Deactivate"``,
which the counter's final state then pulses to take the barrier down).
Three more relays, ``"Set Scan Holo to Dim"`` (one per post), are the ones
that leave the scan hologram dimmed and the scan marker spent.

A new game has none of that remembered. ``make_room_pre_solved`` stands in
for it: a ``Timer`` that starts with the room (like
``elevator_prescan_patch``'s) and, when it fires 1 ms later, sends exactly
what those six relays' ``Active`` connections would have sent, in the same
order. Script messages are queued, so the order is the order they are
handled in -- the same sequence a reload produces.

SCLY only, no DOL patch. The asset ids are the same on NTSC-U and PAL.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from retro_data_structures.formats.mrea import Area

PHAZON_SITE_MLVL = 0x42B935E4
"""Agon Wastes / Dark Agon Wastes."""

PHAZON_SITE_MREA = 0x200EF5E7

# (instance id, name) of every memory relay whose ``Active`` connections a
# reload would fire, in the order they are replayed: the three "Stay Solved"
# steps first, then the three scan holograms.
SOLVED_RELAYS = (
    (0x00460222, "Stay Solved 1"),
    (0x00460223, "Stay Solved 2"),
    (0x00460224, "Stay Solved 3"),
    (0x004601FE, "Set Scan Holo to Dim"),
    (0x0046020F, "Set Scan Holo to Dim"),
    (0x0046021F, "Set Scan Holo to Dim"),
)

TIMER_NAME = "Timer - Pre-scan Phazon Site"
START_DELAY_SECONDS = 0.001


def make_room_pre_solved(editor: Any, mlvl: Any, area: Area) -> None:
    """Adds the timer that replays the solved state (see module docstring)."""
    from retro_data_structures.enums.echoes import State
    from retro_data_structures.properties.echoes.archetypes.EditorProperties import EditorProperties
    from retro_data_structures.properties.echoes.objects.Timer import Timer

    relays = []
    for instance_id, name in SOLVED_RELAYS:
        relay = area.get_instance(instance_id)
        assert relay.name == name, f"{area.name}: instance {instance_id:#x} is {relay.name!r}, expected {name!r}"
        relays.append(relay)

    timer = area.get_layer("Default").add_instance_with(
        Timer(
            editor_properties=EditorProperties(name=TIMER_NAME),
            time=START_DELAY_SECONDS,
            auto_start=True,
        )
    )
    sent = 0
    for relay in relays:
        for connection in list(relay.connections):
            if connection.state == State.Active:
                timer.add_connection(State.Zero, connection.message, area.get_instance(connection.target))
                sent += 1
    assert sent, f"{area.name}: none of the solved-state relays had an Active connection"


def register(area_patcher: AreaPatcher) -> None:
    """Registers ``make_room_pre_solved`` against Phazon Site."""
    area_patcher.add_raw_function(PHAZON_SITE_MLVL, PHAZON_SITE_MREA, make_room_pre_solved)


@contextlib.contextmanager
def installed():
    """Hooks ``register`` into the one ``_apply_patches`` call, the same way
    ``patcher_runner.flying_ing_caches_shootable_installed`` does."""
    from open_prime_rando.echoes import patcher as opr_patcher

    original_register_world_changes = opr_patcher.register_world_changes

    def _register_world_changes_with_phazon_site(area_patcher: AreaPatcher, world_changes: list[Any]) -> None:
        original_register_world_changes(area_patcher, world_changes)
        register(area_patcher)

    opr_patcher.register_world_changes = _register_world_changes_with_phazon_site
    try:
        yield
    finally:
        opr_patcher.register_world_changes = original_register_world_changes
