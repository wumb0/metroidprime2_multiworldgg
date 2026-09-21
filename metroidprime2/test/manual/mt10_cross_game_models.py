"""MT10 -- every cross-game item model loads without crashing the game.

The highest-risk cosmetic path: ``VariaSuit`` once crashed Echoes, and the
experimental table is explicitly unverified. Generation only -- no ROMs are
needed for the companion slots.
"""

from __future__ import annotations

from ...items import ITEM_TABLE
from ...locations import LOCATION_TABLE
from ...patch_data import (
    _CROSS_GAME_ITEM_NAMES,
    _CROSS_GAME_MODEL_OVERRIDES,
    _EXPERIMENTAL_CROSS_GAME_ITEM_NAMES,
)
from . import harness, presets, routes
from .harness import ManualTest, SlotSpec, Step

_SLUG = "mt10_cross_game_models"
_COMPANION_GAMES: tuple[str, ...] = (
    "Metroid Prime",
    "Metroid: Zero Mission",
    "Metroid Fusion",
    "Super Metroid",
)

# All cross-game (game, item) -> our item entries, in a stable order.
_ENTRIES: list[tuple[str, str, str]] = [
    (game, their_name, our_name)
    for game in _COMPANION_GAMES
    for (entry_game, their_name), our_name in sorted(_CROSS_GAME_ITEM_NAMES.items())
    if entry_game == game
]


def _model_for(game: str, their_name: str, our_name: str) -> str:
    return _CROSS_GAME_MODEL_OVERRIDES.get((game, their_name), ITEM_TABLE[our_name].model)


def _locations() -> list[int]:
    """Closest-to-start pickup indices, one per cross-game entry."""
    distances = routes.door_distance("Temple Grounds/Landing Site")
    ordered = sorted(
        range(len(LOCATION_TABLE)),
        key=lambda index: (
            distances.get((LOCATION_TABLE[index].region, LOCATION_TABLE[index].area), 999),
            index,
        ),
    )
    return ordered[: len(_ENTRIES)]


def _companions() -> list[SlotSpec]:
    locations = _locations()
    by_game: dict[str, list[tuple[str, str, str, int]]] = {game: [] for game in _COMPANION_GAMES}
    for (game, their_name, our_name), location in zip(_ENTRIES, locations, strict=True):
        by_game[game].append((their_name, our_name, game, location))

    companions: list[SlotSpec] = []
    for game in _COMPANION_GAMES:
        plando = [
            {
                "item": their_name,
                "location": LOCATION_TABLE[location].name,
                "world": _SLUG,
                "from_pool": True,
            }
            for their_name, _our_name, _game, location in by_game[game]
        ]
        companions.append(SlotSpec(name=game.replace(":", "").replace(" ", ""), game=game, plando=plando))
    return companions


def _notes() -> list[str]:
    locations = _locations()
    lines = ["room -> (source game, item, expected MP2 model):"]
    for (game, their_name, our_name), location in zip(_ENTRIES, locations, strict=True):
        lines.append(
            f"  `{LOCATION_TABLE[location].name}` <- ({game}, {their_name}, "
            f"`{_model_for(game, their_name, our_name)}`)"
        )
    experimental = sorted(
        f"{game}/{name}" for game, name in _EXPERIMENTAL_CROSS_GAME_ITEM_NAMES
    )
    lines.append("entries from the *experimental* table (highest crash risk): " + ", ".join(experimental))
    return lines


TEST = ManualTest(
    slug=_SLUG,
    title="Cross-game models: every mapped model loads without crashing",
    priority="P1",
    proves="every cross-game model (verified and experimental) loads without crashing",
    seed=1_000_010,
    config_sha256="99502d9d2887e33856f3d15261834c96d0e544c2aed8795b9f22e15451c4fbd8",
    options=presets.merge(presets.NO_RANDO_OPTIONS, {"display_nonlocal_items": "match_game"}),
    start_inventory=dict(presets.ALL_ITEMS_START),
    companions=_companions(),
    notes=_notes(),
    steps=[
        Step(
            "Start the game and **walk into every room listed in the notes**, without collecting "
            "anything.",
            "No crash on area load -- crashes happen when the room loads, before you reach the pickup.",
        ),
        Step(
            "Collect each listed pickup.",
            "Each model matches the printed expected model; unmapped items fall back to the generic "
            "Energy Transfer Module.",
        ),
    ],
    pass_criteria=[
        "No crash on any room load.",
        "Every pickup shows the expected model.",
        "Anything without a curated match falls back to the generic model.",
    ],
    on_failure=[
        (
            "Move the offending entry out of `_EXPERIMENTAL_CROSS_GAME_ITEM_NAMES` (as that "
            "table's comment instructs) rather than reverting the feature."
        ),
        "`patch_data._pickup_appearance` / `_CROSS_GAME_MODEL_OVERRIDES`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
