"""Goal warps: for the two boss-skipping ``goal`` settings, send the player
straight to the Credits (``!!game_end_part3``, ``constants.CREDITS_MREA``)
the moment the goal condition is met, instead of making them play on.

* ``keys``: on arriving in Sky Temple Energy Controller -- the first room
  past the Sky Temple Gateway's key gate.
* ``emperor_ing``: on arriving back in Sky Temple Gateway after Emperor Ing
  is dead, where the Dark Samus 3 & 4 fight would otherwise start.

Like ``sky_temple_key_gate_patch.py`` this is a pure SCLY edit of one room
each (no DOL patch), and reuses the room's own arrival hook so nothing needs
a new trigger volume:

**Sky Temple Energy Controller**: the teleporter arrival spawn point
("Inital Spawn Point 001", sic) on the "Teleport Arrival" layer fires the
arrival cinematics -- "Finish Cinema Start" (every visit after the first)
and "Final Boss Intro" (first visit) -- plus a layer reset. The two
cinematic starts are cut and a timer feeding a ``WorldTeleporter`` is
started instead; the layer reset is left alone. The timer and teleporter
live on the always-active Default layer because the reset unloads the
"Teleport Arrival" layer on the same frame.

**Sky Temple Gateway**: Emperor Ing's death (Sanctum's escape-sequence
setup) increments the Gateway's persistent "Dark Samus Battle3 Intro" layer
through a cross-area ``ScriptLayerController``, so that layer is active on
the first Gateway load after the boss and only then. Its
``OcclusionRelay`` starts the intro cinematic on load; that one connection
is repointed at the same timer/teleporter pair. The layer is only ever
unloaded by the intro itself, which no longer runs, so every later Gateway
load warps too.

The Credits area is self-contained -- its own ``OcclusionRelay`` runs the
ending cinematic and docks onward to the credits -- and is also what the
client's memory read already treats as the end of the game, so reaching it
reports the goal with no further client-side detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import constants

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from retro_data_structures.formats.mrea import Area

WARP_DELAY_SECONDS = 1.0
"""Pause between arrival and the warp: long enough for the player to have
spawned and for the client's 0.5s area poll to see the room, short enough
to read as part of the arrival."""

_DEFAULT_LAYER = "Default"

_ENERGY_CONTROLLER_ARRIVAL_LAYER = "Teleport Arrival"
_ENERGY_CONTROLLER_SPAWN = "Inital Spawn Point 001"
_ENERGY_CONTROLLER_CINEMATIC_STARTS = frozenset({"Finish Cinema Start", "Final Boss Intro"})

_GATEWAY_INTRO_LAYER = "Dark Samus Battle3 Intro"
_GATEWAY_INTRO_START = "Cinema Start"


def _add_credits_warp(area: Area) -> Any:
    """Adds the delay timer and the Credits ``WorldTeleporter`` to the
    area's Default layer, wired timer -> teleporter. Returns the timer; the
    caller starts it from the room's own arrival hook."""
    from retro_data_structures.enums.echoes import Message, State
    from retro_data_structures.properties.echoes.archetypes.EditorProperties import EditorProperties
    from retro_data_structures.properties.echoes.objects import Timer, WorldTeleporter

    layer = area.get_layer(_DEFAULT_LAYER)
    timer = layer.add_instance_with(
        Timer(
            editor_properties=EditorProperties(name="AP Goal Warp Delay"),
            time=WARP_DELAY_SECONDS,
            auto_reset=False,
            auto_start=False,
        )
    )
    teleporter = layer.add_instance_with(
        WorldTeleporter(
            editor_properties=EditorProperties(name="AP Goal Warp To Credits", active=True),
            world=constants.TEMPLE_GROUNDS_MLVL,
            area=constants.CREDITS_MREA,
            elevator=-1,
            is_teleport=False,
            is_fade_white=False,
        )
    )
    timer.add_connection(State.Zero, Message.SetToZero, teleporter)
    return timer


def warp_to_credits_from_energy_controller(editor: Any, mlvl: Any, area: Area) -> None:
    """``keys`` goal: swaps the arrival cinematics for the Credits warp
    (see the module docstring). Registered only against Sky Temple Energy
    Controller."""
    from retro_data_structures.enums.echoes import Message, State

    spawn = area.get_layer(_ENERGY_CONTROLLER_ARRIVAL_LAYER).get_instance(_ENERGY_CONTROLLER_SPAWN)
    cinematic_starts = [
        c
        for c in spawn.connections
        if c.state == State.Zero and area.get_instance(c.target).name in _ENERGY_CONTROLLER_CINEMATIC_STARTS
    ]
    assert len(cinematic_starts) == len(_ENERGY_CONTROLLER_CINEMATIC_STARTS), (
        f"{area.name}: expected {len(_ENERGY_CONTROLLER_CINEMATIC_STARTS)} arrival cinematic connections "
        f"on {_ENERGY_CONTROLLER_SPAWN!r}, found {len(cinematic_starts)}"
    )
    for connection in cinematic_starts:
        spawn.remove_connection(connection)

    spawn.add_connection(State.Zero, Message.ResetAndStart, _add_credits_warp(area))


def warp_to_credits_from_gateway(editor: Any, mlvl: Any, area: Area) -> None:
    """``emperor_ing`` goal: swaps the Dark Samus intro cinematic for the
    Credits warp (see the module docstring). Registered only against Sky
    Temple Gateway."""
    from retro_data_structures.enums.echoes import Message, State

    intro_start = area.get_layer(_GATEWAY_INTRO_LAYER).get_instance(_GATEWAY_INTRO_START)
    triggers = [
        (instance, connection)
        for instance, connection in area.get_all_connections_to(intro_start.id)
        if connection.state == State.InternalState01 and connection.message == Message.SetToZero
    ]
    assert len(triggers) == 1, (
        f"{area.name}: expected exactly one InternalState01 SetToZero connection to {_GATEWAY_INTRO_START!r}, "
        f"found {len(triggers)}"
    )
    relay, connection = triggers[0]
    relay.remove_connection(connection)
    relay.add_connection(State.InternalState01, Message.ResetAndStart, _add_credits_warp(area))


def register(area_patcher: AreaPatcher, goal: int) -> None:
    """Registers the warp(s) the given ``goal`` needs. ``both_bosses`` needs
    none; ``keys`` never reaches the Gateway after Ing, so it only gets the
    Energy Controller warp."""
    if goal == constants.GOAL_KEYS:
        area_patcher.add_raw_function(
            constants.GREAT_TEMPLE_SKY_TEMPLE_MLVL,
            constants.SKY_TEMPLE_ENERGY_CONTROLLER_MREA,
            warp_to_credits_from_energy_controller,
        )
    elif goal == constants.GOAL_EMPEROR_ING:
        area_patcher.add_raw_function(
            constants.TEMPLE_GROUNDS_MLVL,
            constants.SKY_TEMPLE_GATEWAY_MREA,
            warp_to_credits_from_gateway,
        )
