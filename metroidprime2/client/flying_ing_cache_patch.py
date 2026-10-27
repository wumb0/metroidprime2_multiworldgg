"""Flying Ing Caches that can be shot without the Dark Visor
(``flying_ing_caches_without_dark_visor``).

Each of the nine Sky Temple Keys sits in a Flying Ing Cache, and all nine
rooms (and only those nine, across every area of the five worlds) build it
from the same script objects, identical between NTSC-U and PAL:

* ``PLAT "War Chest"``: the cache you see. It moves along waypoints and
  carries everything else below as platform slaves (its ``Play ->
  Activate`` connections).
* ``ACTR "Collision Dummy_Dark Visor"``: what a first shot actually hits.
  Inactive in the SCLY, 1 HP, drawn with the invisible collision-cube model
  and a zero targetable-visor mask (``CActor::m_targetableVisorFlags``, so it
  can't be locked onto).
* ``PLCT "DARK VISOR DETECTOR"``: a PlayerController whose ``Entered`` /
  ``Exited`` fire as the Dark Visor goes on and off. ``Entered`` activates
  the War Chest and the dummy; ``Exited`` deactivates both.

So outside the Dark Visor there is nothing in the room for a shot to hit.
The dummy's ``Damage`` deactivates the detector, and its ``Dead`` activates
the War Chest, ``ACTR "Collision Dummy_Other Visor"`` (the 50 HP hitbox
shot in any visor from then on) and ``PLCT "DARK VISOR DETECTOR_2"``. That
is why one hit makes the cache visible for good.

``make_cache_shootable`` makes the dummy start active and drops the
detector's ``Exited -> Deactivate`` on it, so nothing turns it off again
until it dies. The War Chest still only shows in the Dark Visor, so the
cache stays invisible but takes a hit at the War Chest's position; while
it's hidden the War Chest is inactive and doesn't move. Vanilla already
has this state: after the first hit, ``DARK VISOR DETECTOR_2`` hides the
War Chest in the Dark Visor while ``Collision Dummy_Other Visor`` stays
active and shootable.

SCLY only, no DOL patch. Dark Oasis keeps its cache on the "2nd pass"
layer, so there it still only appears once vanilla turns that layer on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from retro_data_structures.formats.mrea import Area

# (mlvl, mrea) of each Sky Temple Key room. Asset ids are the same on NTSC-U
# and PAL.
FLYING_ING_CACHE_ROOMS = {
    (0x42B935E4, 0xEA79522C): "Battleground",
    (0x42B935E4, 0x99FB957F): "Dark Oasis",
    (0x3DFD2249, 0x14E2C3A6): "Poisoned Bog",
    (0x3DFD2249, 0xBBE4B3AE): "Dungeon",
    (0x1BAA96C2, 0xF3FA4121): "Hive Entrance",
    (0x1BAA96C2, 0xF24EF6B4): "Hive Dynamo Works",
    (0x3BFA3EFF, 0x749E82E3): "Ing Reliquary",
    (0x3BFA3EFF, 0x16E116B4): "Defiled Shrine",
    (0x3BFA3EFF, 0x9FD196DF): "Accursed Lake",
}

DETECTOR_NAME = "DARK VISOR DETECTOR"
DUMMY_NAME = "Collision Dummy_Dark Visor"


def make_cache_shootable(editor: Any, mlvl: Any, area: Area) -> None:
    """Leaves the cache's first-hit dummy active outside the Dark Visor
    (see module docstring)."""
    from retro_data_structures.enums.echoes import Message, State
    from retro_data_structures.properties.echoes.objects import Actor

    detector = area.get_instance(DETECTOR_NAME)
    dummy = area.get_instance(DUMMY_NAME)
    hides = [
        c
        for c in detector.connections
        if c.state == State.Exited and c.message == Message.Deactivate and c.target == dummy.id
    ]
    assert len(hides) == 1, (
        f"{area.name}: expected exactly one Exited -> Deactivate from {DETECTOR_NAME!r} to {DUMMY_NAME!r}, "
        f"found {len(hides)}"
    )
    detector.remove_connection(hides[0])
    with dummy.edit_properties(Actor) as props:
        props.editor_properties.active = True


def register(area_patcher: AreaPatcher) -> None:
    """Registers ``make_cache_shootable`` against every key room."""
    for mlvl_id, mrea_id in FLYING_ING_CACHE_ROOMS:
        area_patcher.add_raw_function(mlvl_id, mrea_id, make_cache_shootable)
