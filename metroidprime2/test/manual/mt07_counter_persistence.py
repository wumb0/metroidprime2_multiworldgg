"""MT07 -- the pickup counters survive save/quit/reload and checkpoints."""

from __future__ import annotations

from ...locations import LOCATION_TABLE
from . import harness, presets
from .harness import ManualTest, Step

# Three easy pickups in the Hive/ship area, near the Temple Grounds save
# stations. Any class is fine -- the subject is the counter, not the items.
_PLAN: list[tuple[int, str]] = [
    (0, "Missile Expansion"),
    (2, "Missile Expansion"),
    (4, "Energy Tank"),
]

TEST = ManualTest(
    slug="mt07_counter_persistence",
    title="Persistence: the pickup counters survive save/quit/reload and checkpoints",
    priority="P0",
    proves=(
        "the pickup bitmask counters persist across saves and checkpoint reloads with no lost or "
        "doubled checks"
    ),
    seed=1_000_007,
    config_sha256="cd8c9f77f91b3d322888cbab79d701a3bd4fb27be75a7c4e04576768998fd07b",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS),
    start_inventory=dict(presets.ALL_ITEMS_START),
    plando=[
        {"item": item, "location": LOCATION_TABLE[index].name, "from_pool": True}
        for index, item in _PLAN
    ],
    steps=[
        Step(
            "With the client attached, collect pickup 1.",
            "Exactly one location check is reported and the item is granted.",
        ),
        Step(
            "Close the client, collect pickup 2, save at a save station, quit to the main menu, and "
            "reload the save.",
            "The game returns to the loaded save with pickup 2 collected.",
        ),
        Step(
            "Reopen the client and connect.",
            "Pickup 2 is reported now (the counter survived the save), and the inventory is rebuilt "
            "from ReceivedItems with no duplicates.",
        ),
        Step(
            "With the client attached, collect pickup 3, then die before saving and reload the "
            "checkpoint.",
            "No double credit and no lost check; the item is still in the inventory (it comes from "
            "the server, not the save file).",
        ),
    ],
    pass_criteria=[
        "Pickup 2 collected while detached is reported after reconnect.",
        "No check is credited twice.",
        "Inventory rebuilt from ReceivedItems is idempotent.",
    ],
    on_failure=[
        (
            "`client/patcher_runner.patch_iso_with_ap`'s pre-`_apply_patches` DOL writes "
            "(`powerup_should_persist` / `powerup_max` for every "
            "`constants.PICKUP_COUNTER_ITEMS` id)"
        ),
        "`client/versions.py` offsets for this build",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
