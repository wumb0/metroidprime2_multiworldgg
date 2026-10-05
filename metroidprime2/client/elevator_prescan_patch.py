"""Pre-scanned elevators (``pre_scan_elevators``): replaces open-prime-rando's
``auto_enabled_elevator_patches.patch_elevator``, which never took effect.

Each of the 15 cross-region transport rooms gates its departure on a
persistent "Memory Relay - dim scan holo": scanning the hologram pillar
fires ``Scan Hologram Scan``'s ``ScanDone``, which pulses
"Relay - connect here to dim", which ``Activate``s that memory relay, which
in turn starts "Delayed Activator Activation" and from there enables the
departure trigger, keybeam and hologram. Activating the memory relay by
script is therefore exactly "pre-scanned", and the relay ids in
``ELEVATOR_MEMORY_RELAY_PER_MREA`` are right (checked against all 15 rooms of
a retail ISO).

The upstream helper adds a ``Timer(auto_start=True, time=0.001)`` wired to
that relay, but creates it with ``EditorProperties(active=False)``. An
inactive script object is never thought, so the timer never ran and nothing
was ever activated -- the elevators still needed their pillar scanned.
Every other auto-start timer open-prime-rando adds leaves ``active`` at its
default of True. This version is identical apart from that.

Upstream's relay table also omits the Temple Grounds end of the three Great
Temple elevators (Temple Transport A/B/C in Temple Grounds); only the Great
Temple end is listed. Those rooms have the identical pillar and relay, so
``EXTRA_MEMORY_RELAY_PER_MREA`` adds them. A sweep of every area of the five
main worlds finds no other elevator with a scan pillar: the Aerie /
Aerie Transport Station pair and the Sky Temple Gateway / Energy Controller
pair have no scan gate at all, so nothing needs pre-scanning there.

The timer fires 0.001s after the room loads, before "Setup Departure
Elevator" (0.02s) that the memory relay deactivates, so the room comes up
in its scanned state exactly as it would on a return visit.
"""

from __future__ import annotations

import contextlib
import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from open_prime_rando.patcher_editor import PatcherEditor
    from retro_data_structures.formats.mlvl import Mlvl
    from retro_data_structures.formats.mrea import Area

# (mlvl, mrea) -> "Memory Relay - dim scan holo" instance id, for the
# transports upstream forgot (see module docstring).
EXTRA_MEMORY_RELAY_PER_MREA = {
    (0x3BFA3EFF, 0x503A0640): 0x003600C3,  # Temple Grounds / Temple Transport A
    (0x3BFA3EFF, 0x4CC37F4A): 0x0020003D,  # Temple Grounds / Temple Transport B
    (0x3BFA3EFF, 0xADED752E): 0x00090063,  # Temple Grounds / Temple Transport C
}

TIMER_NAME = "Timer - Auto enable elevator"
AUTO_ENABLE_DELAY_SECONDS = 0.001


def patch_elevator(editor: PatcherEditor, mlvl: Mlvl, area: Area, memory_relay_id: int) -> None:
    """Activates the elevator's scan memory relay shortly after room load."""
    from retro_data_structures.enums.echoes import Message, State
    from retro_data_structures.properties.echoes.archetypes.EditorProperties import EditorProperties
    from retro_data_structures.properties.echoes.objects.Timer import Timer

    relay = area.get_instance(memory_relay_id)
    timer = area.get_layer("Default").add_instance_with(
        Timer(
            editor_properties=EditorProperties(name=TIMER_NAME),
            time=AUTO_ENABLE_DELAY_SECONDS,
            auto_start=True,
        )
    )
    timer.add_connection(State.Zero, Message.Activate, relay)


def register_extra(area_patcher: AreaPatcher) -> None:
    """Registers ``patch_elevator`` for the rooms in ``EXTRA_MEMORY_RELAY_PER_MREA``."""
    for (mlvl_id, mrea_id), memory_relay_id in EXTRA_MEMORY_RELAY_PER_MREA.items():
        area_patcher.add_raw_function(
            mlvl_id,
            mrea_id,
            functools.partial(patch_elevator, memory_relay_id=memory_relay_id),
        )


@contextlib.contextmanager
def installed():
    """Fixes open-prime-rando's pre-scan for the duration of one
    ``_apply_patches`` call: swaps its ineffective ``patch_elevator`` for the
    one above (its ``register`` looks the function up in its module globals
    when called, so replacing the attribute is enough) and has ``register``
    also cover ``EXTRA_MEMORY_RELAY_PER_MREA``. The ``auto_enabled_elevators``
    gate stays upstream's: ``register`` is only called when it is on."""
    from open_prime_rando.echoes.elevators import auto_enabled_elevator_patches as upstream

    original_patch_elevator = upstream.patch_elevator
    original_register = upstream.register

    def _register_with_extras(area_patcher: AreaPatcher) -> None:
        original_register(area_patcher)
        register_extra(area_patcher)

    upstream.patch_elevator = patch_elevator
    upstream.register = _register_with_extras
    try:
        yield
    finally:
        upstream.patch_elevator = original_patch_elevator
        upstream.register = original_register
