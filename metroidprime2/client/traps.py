"""Trap items: one-shot detrimental effects the client applies on receipt.

Unlike every other item, a trap is an *event*, not state: the capacity model
in ``receive_items.py`` re-derives the whole inventory from the full received
list each tick and is idempotent, so a trap needs its own record of which
received items it has already been applied for. That record is an
``items_received`` position persisted in AP DataStorage
(``constants.TRAP_INDEX_DATASTORAGE_KEY``) rather than in the save, so
reconnecting, restarting the client or loading an older save never replays a
trap. This module holds the pure parts (what is pending, what the effect
computes); ``client.py`` drives them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..items import TRAP_ITEM_NAMES

DAMAGE_TRAP = "Damage Trap"
AMMO_DEPLETION_TRAP = "Ammo Depletion Trap"
FREEZE_TRAP = "Freeze Trap"

# Default range (percent of *maximum* energy) a Damage Trap removes; the real
# range comes from the ``damage_trap_min_percent`` / ``damage_trap_max_percent``
# slot data.
DEFAULT_DAMAGE_PERCENT_RANGE = (25, 75)

# Inventory slots the Ammo Depletion Trap zeroes: Power Bombs, Missiles,
# Dark Ammo, Light Ammo (the same ids ``receive_items.py`` computes
# capacities for).
AMMO_ITEM_IDS: tuple[int, ...] = (43, 44, 45, 46)

# Minimum seconds between two applied traps, so a backlog received while
# offline (or a burst of traps in one multiworld release) drips out.
MIN_TRAP_SPACING = 5.0

ENERGY_TANK_ITEM = 42

# Seconds between requests for the stored trap index while no reply has
# arrived.
INDEX_REQUEST_RETRY = 5.0

# The Freeze Trap opens a window (``freeze_trap_duration`` seconds, from slot
# data) during which the player is frozen at random moments. Each freeze lasts
# a random time between ``freeze_trap_min_seconds`` and
# ``freeze_trap_max_seconds`` (slot data; DEFAULT_FREEZE_LENGTH_RANGE if
# absent) and the next one comes a random gap after the
# previous one took hold (``freeze_trap_min_gap_seconds`` /
# ``freeze_trap_max_gap_seconds``, default DEFAULT_FREEZE_GAP_RANGE; all in
# seconds; mashing jump still breaks a freeze early).
DEFAULT_FREEZE_LENGTH_RANGE = (4, 6)
DEFAULT_FREEZE_GAP_RANGE = (5, 20)

# ``CPlayer::Freeze`` quietly refuses in some player states (morph ball
# transitions and the like); after a refusal the client tries again this many
# seconds later.
FREEZE_RETRY_DELAY = 1.0


@dataclass
class TrapState:
    # ``items_received`` positions below this have been handled. None until
    # the DataStorage reply arrives; nothing is applied before that.
    processed_index: int | None = None
    index_requested_at: float = 0.0
    # (position, name) of a trap whose HUD message went out and whose effect
    # is waiting for the game to confirm it consumed that message.
    announced: tuple[int, str] | None = None
    last_applied: float = 0.0
    # Freeze Trap window (``time.time()`` stamps): random freezes happen
    # until ``freeze_window_end``, the next one no sooner than
    # ``next_freeze_at``. ``freeze_armed`` means a freeze call has been
    # sent and its result (did ``mFrozenTimeout`` go positive) is checked
    # on the next free tick.
    freeze_window_end: float = 0.0
    next_freeze_at: float = 0.0
    freeze_armed: bool = False
    # Percent of maximum energy the announced Damage Trap will remove; rolled
    # when it is announced so the HUD memo can state it.
    damage_percent: int = 0
    # The window has closed but its "worn off" HUD message hasn't gone out yet.
    freeze_over_pending: bool = False


def max_health(energy_per_tank: int, energy_tanks: int) -> float:
    """The game's ``CalculateHealth``: ``energy_per_tank`` per tank plus a
    base of ``energy_per_tank - 1``."""
    return float(energy_per_tank * (energy_tanks + 1) - 1)


def plan_damage(health: float, max_energy: float, percent: float) -> float:
    """Health after a Damage Trap: ``percent`` of ``max_energy`` removed,
    never below 1 (a trap cannot kill) and never raising health."""
    return min(health, max(1.0, health - percent / 100 * max_energy))


def random_damage_percent(rng: random.Random, low: int, high: int) -> int:
    """A whole percent in ``[low, high]``; the bounds may come in either order."""
    return rng.randint(min(low, high), max(low, high))


def random_freeze_length(rng: random.Random, low: float, high: float) -> float:
    """Seconds for one freeze, in ``[low, high]`` (bounds in either order)."""
    return rng.uniform(min(low, high), max(low, high))


def random_freeze_gap(rng: random.Random, low: float, high: float) -> float:
    """Seconds until the next freeze, in ``[low, high]`` (bounds in either order)."""
    return rng.uniform(min(low, high), max(low, high))


def pending_traps(received: list[str], first_non_starting: int, processed_index: int) -> list[tuple[int, str]]:
    """``(position, trap name)`` for each trap in ``received`` not yet
    handled, in order. Positions below ``first_non_starting`` are the start
    inventory and never trigger anything."""
    start = max(processed_index, first_non_starting)
    return [(index, name) for index, name in enumerate(received) if index >= start and name in TRAP_ITEM_NAMES]


FREEZE_OVER_MESSAGE = "The Freeze Trap has worn off."


def _describe_duration(seconds: int) -> str:
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} seconds"


def trap_message(trap_name: str, freeze_window: int, damage_percent: int = 0) -> str:
    if trap_name == DAMAGE_TRAP:
        return f"Damage Trap! You lose {damage_percent}% of your maximum energy."
    if trap_name == AMMO_DEPLETION_TRAP:
        return "Ammo Depletion Trap! Your ammo is gone."
    if trap_name == FREEZE_TRAP:
        return f"Freeze Trap! You will freeze at random for {_describe_duration(freeze_window)}."
    return f"{trap_name}!"
