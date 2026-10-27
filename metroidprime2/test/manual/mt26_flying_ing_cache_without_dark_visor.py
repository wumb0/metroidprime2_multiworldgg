"""MT26 -- `flying_ing_caches_without_dark_visor`: shoot a Sky Temple Key cache you can't see."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt26_flying_ing_cache_without_dark_visor"
_LOCATION = "Sky Temple Grounds: Defiled Shrine - Pickup (Sky Temple Key 8)"

TEST = ManualTest(
    slug=_SLUG,
    title="Flying Ing Caches Without Dark Visor: an invisible key cache takes a combat-visor hit",
    priority="P1",
    proves=(
        "client/flying_ing_cache_patch.py leaves each key cache's `Collision Dummy_Dark Visor` active "
        "outside the Dark Visor, so a shot at the hidden cache lands, reveals it and the key drops "
        "as in vanilla"
    ),
    seed=1_000_026,
    config_sha256="b421579aa828b419f9c2c0d017843c6ef5fcba6183f99489c502136f1ef5b55e",
    starting_room="Sky Temple Grounds/Defiled Shrine/Door to Shrine Access",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.GOD_MODE_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"flying_ing_caches_without_dark_visor": True},
    ),
    start_inventory=presets.merge_inventory(
        presets.ALL_ITEMS_START,
        presets.GOD_MODE_START_INVENTORY,
        {"Dark Visor": 0},
    ),
    setup=[
        "Host the generated multiworld and keep the server console open; the last steps need it.",
    ],
    notes=[
        "You start with everything except the Dark Visor.",
        (
            "The cache hangs about 3 m above head height, roughly 15 m south-west of the safe zone crystal "
            "on the west side of the room (the one farthest from the door you spawn at). An invisible field "
            "under it knocks you back; that happens in vanilla too and is the easiest way to find the spot."
        ),
        "While the cache is invisible it doesn't move, so it stays where it started.",
    ],
    steps=[
        Step(
            "Start New Game, connect the client and look around Defiled Shrine.",
            "No Ing Cache is visible anywhere.",
        ),
        Step(
            "Walk to the spot described in the notes until the invisible field knocks you back, then back "
            "off a few metres.",
            "You get pushed away from an empty-looking spot.",
        ),
        Step(
            "Without locking on, fire Power Beam shots upward through the space above that spot.",
            "One shot hits something: the cache cries out, appears and starts flying its route.",
            why="The first hit kills the 1 HP dummy, which turns the visible cache on (vanilla scripting).",
        ),
        Step(
            "Destroy the now-visible cache and collect the key it drops.",
            f"The cache bursts, the pickup appears and collecting it checks `{_LOCATION}` in the client.",
        ),
        Step(
            "From the server console run `/send <player> Dark Visor`, leave the room, come back and look "
            "around in each visor.",
            "Nothing new appears: the cache is gone for good.",
        ),
    ],
    variants={
        "dark_visor": Variant(
            config_sha256="62c89736dd3c39733bbbb9ad13144a0a2293c28e9b43dddf042c7431ccfeb38f",
            start_inventory={"Dark Visor": 1},
            notes=["You start with everything, the Dark Visor included."],
            steps=[
                Step(
                    "Start New Game, connect the client and switch to the Dark Visor.",
                    "The cache is visible and flying its route, as in vanilla.",
                ),
                Step(
                    "Watch it for a moment, then switch back to the Combat Visor.",
                    "It vanishes. Note where it was.",
                ),
                Step(
                    "Without locking on, shoot the spot where it vanished.",
                    "The shot hits: the cache cries out, appears and starts moving again.",
                    why="Hidden, the cache stops moving, and its hitbox stays where it was.",
                ),
                Step(
                    "Destroy it and collect the key.",
                    f"Collecting it checks `{_LOCATION}`.",
                ),
            ],
            pass_criteria=[
                "With the Dark Visor the cache behaves as in vanilla.",
                "Hidden mid-route, the cache can be shot at the spot where it vanished.",
            ],
        ),
        "off": Variant(
            config_sha256="10a6baf52d8b704f7633eaa6a69a2cc14e4d8b368700e01be7cebffcb8de8b16",
            options={"flying_ing_caches_without_dark_visor": False},
            steps=[
                Step(
                    "Start New Game, connect the client, find the spot (see notes) and shoot through the "
                    "space above it, sweeping widely.",
                    "Nothing is ever hit and no cache appears, as in vanilla.",
                ),
            ],
            pass_criteria=["With the option off, shots never hit the hidden cache."],
        ),
    },
    pass_criteria=[
        "The cache can't be seen without the Dark Visor, but a shot at it lands.",
        "After the first hit it is visible and destroyable, and its key checks the location.",
        "No client traceback.",
    ],
    on_failure=[
        "`client/flying_ing_cache_patch.py::make_cache_shootable`",
        "`client/patcher_runner.py::flying_ing_caches_shootable_installed`",
        "`test/test_flying_ing_cache.py`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
