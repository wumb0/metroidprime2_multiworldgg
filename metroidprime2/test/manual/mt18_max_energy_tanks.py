"""MT18 -- max_energy_tanks: the Energy Tank cap in the DOL, client and HUD."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt18_max_energy_tanks",
    title="Max Energy Tanks: the cap can be raised past 14 (experimental)",
    priority="P2",
    proves=(
        "max_energy_tanks rewrites the game's Energy Tank cap, and the client, tracker panel and "
        "starting inventory all clamp to that same value"
    ),
    seed=1_000_018,
    config_sha256="01a3ae839207da2bab95e0af6219ae59b549db26a93ad4840c428879a3e1d187",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"max_energy_tanks": 20, "energy_per_tank": 100},
    ),
    # ALL_ITEMS_START already holds 14 Energy Tanks (the vanilla cap).
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=[
        Step(
            "Connect the client and run `/mp2_debug_inventory`.",
            "Item 42 (Energy Tank) reads 14/14. The tracker panel's tank counter reads 14/20.",
        ),
        Step(
            "Look at the HUD with full health.",
            "The energy readout is 1499 (99 + 14 x 100).",
            why="base health is energy_per_tank - 1, plus energy_per_tank per tank.",
        ),
        Step(
            "From the server console, run `/send <player> Energy Tank` six times, waiting for the "
            "notification each time.",
            "Each send raises the tank count by one and the max health by 100. After the sixth, "
            "`/mp2_debug_inventory` reads item 42 as 20/20, the panel reads 20/20, and full health "
            "is 2099. Health tops up when each tank is granted.",
            why="powerup_max[42] is 20, so the game accepts tanks 15 through 20.",
        ),
        Step(
            "Note how many tank icons the HUD draws, then send two more Energy Tanks.",
            "Item 42 and the panel stay at 20 and full health stays 2099: the extra tanks are "
            "dropped, not stored.",
            why="HUD icon count is cosmetic: the HUD is laid out for 14, so icons past 14 may be "
            "clipped, overlap or be missing. That is expected and not a failure.",
        ),
        Step(
            "Take some damage (a Dark Aether area works), then pause and check the energy readout.",
            "Health drops normally from the 2099 maximum and the number is correct (no wraparound "
            "or negative values).",
        ),
        Step(
            "Save at a save station, quit to the main menu, reload the save and reconnect the "
            "client.",
            "Item 42 still reads 20/20 and full health is still 2099.",
        ),
    ],
    variants={
        "default_cap": Variant(
            config_sha256="92b946e91e4931f300be9ddd23ce926e9ae5dacb7f7335af1d14f75ad3815842",
            options={"max_energy_tanks": 14},
            start_inventory={"Energy Tank": 20},
            steps=[
                Step(
                    "Connect the client and run `/mp2_debug_inventory`.",
                    "Item 42 reads 14/14 although 20 tanks were given at the start. The panel "
                    "reads 14/14 and full health is 1499.",
                    why="the starting inventory is clamped to the cap.",
                ),
                Step(
                    "From the server console, run `/send <player> Energy Tank` twice.",
                    "Nothing changes: item 42 stays 14/14 and full health stays 1499. This is "
                    "vanilla behavior, unchanged by the option.",
                ),
            ],
        ),
        "high": Variant(
            config_sha256="5a8e5161440f9993e3545b0508f02b40b4e064db027375921e7dda3de5cbe446",
            options={"max_energy_tanks": 30},
            start_inventory={"Energy Tank": 30},
            steps=[
                Step(
                    "Connect the client and run `/mp2_debug_inventory`.",
                    "Item 42 reads 30/30. The panel reads 30/30 and full health is 3099.",
                ),
                Step(
                    "Walk around, open the pause screen and the map, and take some damage.",
                    "No crash, freeze or garbled energy readout. The four-digit energy number "
                    "(3099) is displayed and decreases correctly. Missing tank icons past 14 "
                    "are cosmetic and not a failure.",
                    why="this is the stress case for the HUD and the health float.",
                ),
            ],
        ),
    },
    pass_criteria=[
        "With the default cap variant, tanks stop at 14 exactly as in vanilla.",
        "With max_energy_tanks 20, tanks 15-20 are accepted (item 42, panel and max health all "
        "agree) and a 21st is not.",
        "Full health equals 99 + 100 x tanks at every step, and survives a save and reload.",
        "With max_energy_tanks 30 the game stays stable and health values are correct.",
    ],
    on_failure=[
        "`client/patcher_runner.py` (the `powerup_max` write for item 42)",
        "`client/receive_items.py::compute_desired_capacities` (`max_energy_tanks` clamp)",
        "`patch_data.py` (starting-inventory clamp)",
        "`client/item_panel.py` (panel counter)",
    ],
    notes=[
        "EXPERIMENTAL: vanilla caps Energy Tanks at 14 (`powerup_max[42]`); whether the game copes "
        "with more is untested. If tanks past 14 never appear, check that write first.",
        "Cosmetic HUD limits (tank icons past 14) are expected and are not test failures.",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
