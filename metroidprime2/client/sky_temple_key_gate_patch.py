"""Sky Temple Key gate: how many of the 9 keys must actually be held to
unlock Temple Grounds/Sky Temple Gateway's ring of columns (and, downstream,
the Dark Samus 3/4 fight and the Sky Temple elevator), independent of how
many of the 9 keys are shuffled into the item pool as findable pickups
versus handed to the player for free (``sky_temple_keys``/
``sky_temple_keys_required``, PLAN.md section S).

open-prime-rando has no equivalent (checked). Like ``warp_patch.py``, this
is implemented directly against the room's SCLY rather than upstreamed --
unlike warp-to-start, it needs no DOL patch at all, so there is no "DOL"
half to this module.

Reading Sky Temple Gateway's SCLY (retail NTSC-U, via retro_data_structures
against a real ISO) confirms the mechanism: an ``AdvancedCounter`` named
"Count Keys Returned" increments once per Sky Temple Key whose PlayerItem
amount reads 1 -- every key is re-evaluated from scratch by a set of
"Query Key Return" conditional relays whenever "Initiate Returned Key
Tests" pulses them (on room load and after a key is inserted), so this
also covers keys the player already held on first arrival, not just ones
inserted in front of the player. The counter's ``Open`` message to a
``Switch`` named "Got All Keys ?" -- which starts the "Returned All Keys"
sequence that lowers the ring of columns and unlocks everything downstream
-- is wired from the counter's 9th internal state (``InternalState08``;
state N corresponds to N+1 keys held, confirmed by state 2, the 3rd,
driving the "Returned 3 Keys" HUD message). Moving that one connection to
an earlier internal state is the entire patch: every query relay, the
per-key column-raising visuals, and the "Returned N Keys" HUD messages are
all untouched and still track every key the player actually holds, up to
9 -- they just no longer gate progress past ``required``.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from retro_data_structures.formats.mrea import Area

_COUNTER_NAME = "Count Keys Returned"

# Temple Grounds MLVL / Sky Temple Gateway MREA asset ids. Identical between
# NTSC-U and PAL (asset ids only move between the paks that carry an area's
# strings, not the area itself) -- matches
# open_prime_rando.echoes.asset_ids.world.TEMPLE_GROUNDS_MLVL /
# .asset_ids.temple_grounds.SKY_TEMPLE_GATEWAY_MREA, hardcoded here too so
# this module has no import-time dependency on those modules' layout.
_TEMPLE_GROUNDS_MLVL = 0x3BFA3EFF
_SKY_TEMPLE_GATEWAY_MREA = 0x87D35EE4


def set_sky_temple_key_requirement(editor: Any, mlvl: Any, area: Area, required: int) -> None:
    """Rewires ``_COUNTER_NAME``'s ``Open`` connection (see module
    docstring) to fire once ``required`` keys are held instead of all 9.
    Registered only against Sky Temple Gateway (``register`` below), so
    ``area`` is always that room.
    """
    from retro_data_structures.enums.echoes import Message, State

    if not 1 <= required <= 9:
        raise ValueError(f"sky_temple_keys_required must be between 1 and 9, got {required}")
    if required == 9:
        return  # Vanilla behavior; nothing to change.

    counter = area.get_instance(_COUNTER_NAME)
    open_connections = [c for c in counter.connections if c.message == Message.Open]
    assert len(open_connections) == 1, (
        f"{area.name}: expected exactly one Open connection on {_COUNTER_NAME!r}, found {len(open_connections)}"
    )
    open_connection = open_connections[0]

    counter.remove_connection(open_connection)
    counter.add_connection(State[f"InternalState{required - 1:02d}"], Message.Open, open_connection.target)


def register(area_patcher: AreaPatcher, required: int) -> None:
    """Registers the gate rewrite against Sky Temple Gateway alone."""
    area_patcher.add_raw_function(
        _TEMPLE_GROUNDS_MLVL,
        _SKY_TEMPLE_GATEWAY_MREA,
        functools.partial(set_sky_temple_key_requirement, required=required),
    )
