"""MT10 -- every distinct cross-game item *model* loads without crashing.

The highest-risk cosmetic path: ``VariaSuit`` once crashed Echoes. Every
model in ``_CROSS_GAME_ITEM_NAMES``/``_CROSS_GAME_MODEL_OVERRIDES`` has
since been manually validated in-game by this test; re-run it whenever a
new entry is added to either table. Generation only -- no ROMs are needed
for the companion slots.

Simplified scope: this used to plando *every* ``_CROSS_GAME_ITEM_NAMES``
(game, their_name) pair, one pickup per entry. The individual name matches
are hand-curated conceptual matches (see ``patch_data.py``'s comment above
that table) -- they aren't re-verified in-game here, and a wrong one just
falls back to the generic Energy Transfer Module, which is harmless. What
actually needs proving on real hardware/Dolphin is that each distinct OPR
*model* loads/renders without crashing, so this only plandos one
representative (game, their_name) pair per distinct resolved model --
multiple pairs that resolve to the same model prove nothing new.
"""

from __future__ import annotations

from ...items import ITEM_TABLE
from ...locations import LOCATION_TABLE
from ...patch_data import _CROSS_GAME_ITEM_NAMES, _CROSS_GAME_MODEL_OVERRIDES
from . import harness, presets, routes
from .harness import ManualTest, SlotSpec, Step

_SLUG = "mt10_cross_game_models"
# Generate.handle_name() silently truncates every player name to 16 chars
# (e.g. "mt10_cross_game_") before building `world_name_lookup`. The
# companion slots' plando entries target this world by name, so they must
# use the same truncated form or the lookup misses, the plando block is
# dropped with only a log warning, and the item lands wherever the normal
# fill algorithm puts it instead of the room named in the notes/README.
_PRIMARY_PLAYER_NAME = _SLUG.strip()[:16].strip()
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


def _representative_entries() -> list[tuple[str, str, str]]:
    """One (game, their_name, our_name) per distinct resolved model --
    first hit in ``_ENTRIES`` order wins."""
    seen: set[str] = set()
    representatives: list[tuple[str, str, str]] = []
    for game, their_name, our_name in _ENTRIES:
        model = _model_for(game, their_name, our_name)
        if model in seen:
            continue
        seen.add(model)
        representatives.append((game, their_name, our_name))
    return representatives


def _locations() -> list[int]:
    """Closest-to-start pickup indices, one per representative entry."""
    entries = _representative_entries()
    distances = routes.door_distance("Temple Grounds/Landing Site")
    ordered = sorted(
        range(len(LOCATION_TABLE)),
        key=lambda index: (
            distances.get((LOCATION_TABLE[index].region, LOCATION_TABLE[index].area), 999),
            index,
        ),
    )
    return ordered[: len(entries)]


def _companions() -> list[SlotSpec]:
    entries = _representative_entries()
    locations = _locations()
    by_game: dict[str, list[tuple[str, str, str, int]]] = {game: [] for game in _COMPANION_GAMES}
    for (game, their_name, our_name), location in zip(entries, locations, strict=True):
        by_game[game].append((their_name, our_name, game, location))

    companions: list[SlotSpec] = []
    for game in _COMPANION_GAMES:
        if not by_game[game]:
            # Every model this game could contribute was already covered by
            # an earlier companion's entry -- no plando needed for it.
            continue
        plando = [
            {
                "item": their_name,
                "location": LOCATION_TABLE[location].name,
                "world": _PRIMARY_PLAYER_NAME,
                "from_pool": True,
            }
            for their_name, _our_name, _game, location in by_game[game]
        ]
        companions.append(SlotSpec(name=game.replace(":", "").replace(" ", ""), game=game, plando=plando))
    return companions


def _notes() -> list[str]:
    entries = _representative_entries()
    locations = _locations()
    lines = ["room -> (source game, item, expected MP2 model) -- one representative per distinct model:"]
    for (game, their_name, our_name), location in zip(entries, locations, strict=True):
        lines.append(
            f"  `{LOCATION_TABLE[location].name}` <- ({game}, {their_name}, "
            f"`{_model_for(game, their_name, our_name)}`)"
        )
    override_models = sorted(set(_CROSS_GAME_MODEL_OVERRIDES.values()))
    lines.append("models from the override table: " + ", ".join(override_models))
    return lines


TEST = ManualTest(
    slug=_SLUG,
    title="Cross-game models: every distinct mapped model loads without crashing",
    priority="P1",
    proves="every distinct cross-game item model (name-matched and override) loads without crashing",
    seed=1_000_010,
    config_sha256="7c3d55c4d2c96b508bc864467736be9302f1fbecc50fbbdd93d881fc18f921e4",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS, {"display_nonlocal_items": "match_game"}
    ),
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
            "No crash on pickup. The exact name-to-model pairing isn't being re-verified here (that's "
            "a hand-curated, name-matched table); what matters is that the underlying model loads.",
        ),
    ],
    pass_criteria=[
        "No crash on any room load.",
        "No crash on collecting any pickup.",
    ],
    on_failure=[
        (
            "Delete the offending entry from `_CROSS_GAME_ITEM_NAMES` (or "
            "`_CROSS_GAME_MODEL_OVERRIDES`, if that's what supplied the model) rather than "
            "reverting the feature -- it falls back to the generic Energy Transfer Module."
        ),
        "`patch_data._pickup_appearance` / `_CROSS_GAME_MODEL_OVERRIDES`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
