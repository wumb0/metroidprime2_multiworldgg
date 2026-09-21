"""MT08 -- pickups collected while detached decode back to every location.

PLAN.md section P: each pickup ORs one bit into one of four persistent
counters, so any number of pickups collected over any length of disconnect
decodes back to exactly the indices that produced them. This is the test
that the old shared-additive-counter design (and its
``location_reconciliation`` subset-sum fallback, both removed by section P)
could not pass: two pickups collected in one detached window merged into an
ambiguous sum.
"""

from __future__ import annotations

from ...locations import LOCATION_TABLE
from . import harness, presets, routes
from .harness import ManualTest, Step

# One pickup per counter group, closest to Landing Site by door distance --
# collecting all four in one detached window is the cross-counter decode.
_BY_GROUP = routes.pickups_spanning_counter_groups(per_group=2)
_SPREAD: tuple[int, ...] = tuple(indices[0] for indices in sorted(_BY_GROUP.values()))
# Two more pickups, each sharing a counter with one collected above, for
# the several-bits-on-one-counter case (a different decode path than one
# bit per counter).
_SAME_COUNTER: tuple[int, ...] = tuple(_BY_GROUP[0][1:2]) + tuple(_BY_GROUP[1][1:2])
_SINGLE = _BY_GROUP[2][1]
_COLLECTED = (*_SPREAD, *_SAME_COUNTER, _SINGLE)


def _names(indices: tuple[int, ...]) -> str:
    return ", ".join(LOCATION_TABLE[index].name for index in indices)


def _plando() -> list[dict]:
    return [
        {"item": "Missile Expansion", "location": LOCATION_TABLE[index].name, "from_pool": True}
        for index in sorted(set(_COLLECTED))
    ]


TEST = ManualTest(
    slug="mt08_missed_checks",
    title="Missed checks: everything collected while detached is credited, exactly once",
    priority="P0",
    proves=(
        "pickups collected across several counters while the client is detached all decode back to "
        "their own locations, with nothing dropped and nothing invented"
    ),
    seed=1_000_008,
    # Re-pin with --repin after the first build: section P changed this
    # test's plando set, so the previous pin no longer applies.
    config_sha256=None,
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.FAST_RETRY_OPTIONS, presets.GOD_MODE_OPTIONS),
    start_inventory=presets.merge_inventory(presets.ALL_ITEMS_START, presets.GOD_MODE_START_INVENTORY),
    plando=_plando(),
    notes=[
        f"one pickup per counter: {list(_SPREAD)} -> {_names(_SPREAD)}",
        f"two pickups sharing counters already used above: {list(_SAME_COUNTER)} -> {_names(_SAME_COUNTER)}",
        f"final single pickup: {_SINGLE} -> {LOCATION_TABLE[_SINGLE].name}",
        (
            "The picks come from `routes.pickups_spanning_counter_groups`, which derives the counter "
            "group from `pickup_encoding.BITS_PER_COUNTER` -- so they follow the encoding rather than "
            "being hardcoded alongside it."
        ),
    ],
    steps=[
        Step(
            "Connect the client and run `!missing` in the client chat.",
            f"All {len(LOCATION_TABLE)} locations are listed as missing; note the "
            f"{len(set(_COLLECTED))} rooms named above.",
        ),
        Step(
            "Close the client, collect the four one-per-counter pickups, then reopen/connect the client.",
            "All four locations are credited in one go and all four items are granted. The client logs "
            "no warning about stray bits and none about an index that was 'already checked "
            f"server-side'. `!missing` now lists exactly the remaining "
            f"{len(set(_COLLECTED)) - len(_SPREAD)} rooms plus everything untouched -- no location "
            "the tester never visited was credited.",
        ),
        Step(
            "Close the client again, collect the two pickups that share counters with ones already "
            "collected, then reopen/connect.",
            "Both are credited (several bits on one counter decode the same way), both items are "
            "granted, and nothing else changes.",
        ),
        Step(
            "With the client attached, collect the final single pickup.",
            "It credits immediately, the way an attached pickup always has -- the detached runs left "
            "the counters clean rather than poisoning the session.",
        ),
        Step(
            "Optional: reload the save from before the last pickup and collect it a second time while "
            "detached, then reconnect.",
            "This is section P's one known residual failure mode (the same bit collected twice carries "
            "into its neighbour). The client must log the 'already checked server-side' warning rather "
            "than crashing or silently crediting a stranger's location -- the warning existing is the "
            "pass condition here, not the absence of the case.",
        ),
    ],
    pass_criteria=[
        "Every pickup collected while detached is credited to its own location, across all four counters.",
        "No location the tester never collected is ever credited.",
        "No stray-bit warning appears for an ordinary detached run.",
        "A normal attached pickup immediately afterwards still credits.",
    ],
    on_failure=[
        "`pickup_encoding.py` (`counter_and_amount` / `decode`)",
        "`client/client.py::_handle_pickup_counters`",
        "`client/game_interface.py::consume_counters`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
