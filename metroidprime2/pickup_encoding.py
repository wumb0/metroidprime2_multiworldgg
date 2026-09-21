"""One-bit-per-pickup counter layout for Metroid Prime 2: Echoes (PLAN.md
section P), replacing the additive single-counter scheme (section O) and
its decoder, the now-removed ``client/location_reconciliation.py``.

Section O's exact-match fix closed the *false victory* outcome of the old
scheme (one shared counter, item 74, that every pickup ADDs its own
``pickup_index + 1`` to) but deliberately left the underlying channel
unchanged: summing distinct pickups into one accumulator destroys which
pickups produced the sum. ``location_reconciliation``'s subset-sum search
tried to invert that sum against the server's still-missing locations, but
measured against the real 119-pickup layout it drops and misattributes
checks far more often than it recovers them (PLAN.md section P's collision
table), and is provably unfixable from the decoder side alone: preferring
the smallest unique explanation IS the misattribution, and demanding a
globally unique explanation drops nearly every ordinary check once enough
locations are missing. The fix has to be in the encoding, not the decoder.

**The encoding.** Give each pickup index its own bit in one of several
persistent counters, instead of an addend in one shared counter. Addition
of distinct powers of two is bit-set: N pickups collected during any-length
disconnect produce a value that decodes back to exactly those N indices,
with no search, no uniqueness condition, and no guessing.

**Why only 4 counters, and why 30 bits each.** Only 4 of the 8
``PersistentCounterN`` ids are actually free to use: randovania's own
resource allocation (``data/logic_database/header.json``'s
``resource_database.items[*].extra.item_id``) reserves 71/72
(Temporary1/Temporary2, live ammo-conversion scratch items per
``data/pickup_database.json``) and 73 (MissileLauncher, this world's own
"missiles unlocked" flag -- see ``items.py``'s Missile Launcher entry and
``client/receive_items.py``'s ``_MISSILE_LAUNCHER_FLAG``); 74 (Multiworld)
is reserved too, but deliberately, for the goal counter below. That
leaves only 67-70, so 119 pickups need >= 30 usable bits per counter
(``ceil(119 / 4) == 30``), not the naive 15.

15 bits was originally read as a hard constraint:
``ppc_asm.assembler.ppc.li`` is ``addi rD, r0, SIMM16``, and
``Instruction.compose`` asserts ``-32768 <= literal < 32768``, and
``open_prime_rando.dol_patching.all_prime_dol_patches.
adjust_item_amount_patch`` (the obvious way to consume a counter's value)
emits ``li(r5, abs(delta))`` -- a signed 16-bit immediate -- so a delta
above 32767 doesn't fit *that particular instruction sequence*. But
``Pickup.amount``/``capacity_increase`` are signed 32-bit fields
(``BIG_l``), so the real ceiling is far higher; only the ``li``-based
consume patch was ever the bottleneck. ``client/game_interface.py``'s
``_wide_decrement_patch`` composes the amount with ``lis``/``ori`` instead
(both operate on unsigned 16-bit fields, so masking the high/low halves of
any 32-bit amount to ``0xFFFF`` can never fail ``Instruction.compose``'s
range assert) -- raising the practical ceiling to comfortably more than
the 30 bits (``2**30 - 1``) this layout needs. See
``constants.PICKUP_COUNTER_ITEMS``'s docstring for the full reserved-id
accounting, and ``test_pickup_encoding.py`` for the disjointness test that
keeps another id from silently becoming unsafe the same way.

**The goal signal is deliberately not part of this module.** It lives on
its own item (``constants.GOAL_COUNTER_ITEM``, PersistentCounter8 --
randovania's own "Multiworld" allocation) specifically so it can never
alias with a pickup bit, and so "amount nonzero" alone is a correct goal
check regardless of whether the in-ISO ``SetInventoryAmount``
SpecialFunction that writes it sets or adds (PLAN.md section P constraint
5). ``client/client.py`` checks that counter directly; this module only
ever encodes/decodes the 119 real pickups.

Pure module: no Dolphin, no Archipelago imports beyond ``constants``/
``locations``, so it can be imported at generation time (``patch_data.py``,
no patcher stack installed) and at runtime (``client/client.py``) alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import constants
from .locations import LOCATION_TABLE

BITS_PER_COUNTER = constants.BITS_PER_COUNTER
PICKUP_COUNTER_ITEMS = constants.PICKUP_COUNTER_ITEMS

# If the location table ever grows past what this layout can address, fail
# loudly at import time -- silently aliasing two pickups onto the same
# (counter, bit) pair would corrupt both their location checks, and that
# bug would otherwise only surface once someone actually collected both.
assert len(PICKUP_COUNTER_ITEMS) * BITS_PER_COUNTER >= len(LOCATION_TABLE), (
    f"{len(PICKUP_COUNTER_ITEMS)} counters * {BITS_PER_COUNTER} bits each can only address "
    f"{len(PICKUP_COUNTER_ITEMS) * BITS_PER_COUNTER} pickups, but LOCATION_TABLE has "
    f"{len(LOCATION_TABLE)}; add another entry to constants.PICKUP_COUNTER_ITEMS."
)


def counter_and_amount(pickup_index: int) -> tuple[int, int]:
    """The ``(item_id, bit_value)`` one pickup should grant for
    ``pickup_index``. This is the only place ``// BITS_PER_COUNTER`` and
    ``% BITS_PER_COUNTER`` appear -- ``patch_data.py`` calls this at
    generation time to build each pickup's resource, and ``decode`` below
    is its inverse at runtime.
    """
    counter_slot, bit = divmod(pickup_index, BITS_PER_COUNTER)
    return PICKUP_COUNTER_ITEMS[counter_slot], 1 << bit


@dataclass
class Decoded:
    """Result of decoding every pickup counter's live inventory amount.

    ``indices`` -- 0-based pickup indices whose bit was set on some
    counter, sorted ascending across all counters combined (a multi-pickup
    disconnect can spread indices across several counters; the caller
    reports all of them as one ``LocationChecks`` batch).

    ``deltas`` -- ``(item_id, -amount)`` for every counter that had a
    nonzero amount, using the *exact* value read rather than a
    reconstructed mask of only the recognised bits (PLAN.md section P
    point 2) -- consuming anything less would leave a stray bit's
    contribution behind to corrupt a future decode, and consuming a
    blanket zero would wipe out a pickup that lands between this read and
    the consume actually happening.

    ``stray`` -- ``(item_id, mask)`` for bits that don't correspond to any
    real pickup: either past the last real index (e.g. the 4th counter's
    bit 29, deliberately left unused by the slot allocation -- 119
    pickups don't fill all 120 slots 4 counters of 30 bits provide) or
    at/above ``BITS_PER_COUNTER`` entirely, which would mean a counter
    grew past what any pickup could ever legitimately write to it.
    Reported so the caller can warn without dropping the indices that DID
    decode cleanly alongside it.
    """

    indices: list[int] = field(default_factory=list)
    deltas: list[tuple[int, int]] = field(default_factory=list)
    stray: list[tuple[int, int]] = field(default_factory=list)


def decode(inventory: dict[int, tuple[int, int]]) -> Decoded:
    """Decodes every counter in ``PICKUP_COUNTER_ITEMS`` from a
    ``{item_id: (amount, capacity)}`` inventory snapshot -- the shape
    ``game_interface.EchoesInterface.read_inventory`` returns.

    Every counter with a nonzero amount contributes one ``deltas`` entry
    consuming its *exact* current amount (see ``Decoded``'s docstring),
    regardless of whether every bit in it decoded to a real index or not,
    so nothing is ever left behind to alias a later read.
    """
    decoded = Decoded()
    last_valid_index = len(LOCATION_TABLE) - 1
    counter_mask = (1 << BITS_PER_COUNTER) - 1

    for slot, item_id in enumerate(PICKUP_COUNTER_ITEMS):
        amount, _capacity = inventory.get(item_id, (0, 0))
        if amount <= 0:
            continue

        for bit in range(BITS_PER_COUNTER):
            if not amount & (1 << bit):
                continue
            index = slot * BITS_PER_COUNTER + bit
            if index <= last_valid_index:
                decoded.indices.append(index)
            else:
                decoded.stray.append((item_id, 1 << bit))

        overflow = amount & ~counter_mask
        if overflow:
            decoded.stray.append((item_id, overflow))

        decoded.deltas.append((item_id, -amount))

    decoded.indices.sort()
    return decoded
