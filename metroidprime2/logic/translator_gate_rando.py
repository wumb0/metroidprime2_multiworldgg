"""Translator gate color randomization for Metroid Prime 2: Echoes: builds
the per-seed ``{gate_node_id: color_or_None}`` assignment consulted by
``logic/regions.py``'s ``translator_gate_requirement`` override point and by
``patch_data.py``'s ``_translator_gate_modification`` (the same assignment
drives both the logic graph and the in-ISO patch, exactly like
``logic/dock_rando.py``'s ``DockRandoAssignment``).

Mirrors randovania's own translator gate generator step
(``randovania/games/prime2/generator/base_patches_factory.py``'s
``SharedEchoesBasePatches.translator_gates``): "Random" independently picks
one of the four translator colors for every gate; "Random (Unlocked)" adds
a fifth possible outcome, "unlocked" (the gate requires only Scan Visor, no
translator at all -- open-prime-rando has a dedicated "unlocked"
``TranslatorRequirement`` for exactly this, see
``open_prime_rando.echoes.translator_gates.TRANSLATOR_DATA``). Each of the
17 gates is chosen completely independently, with uniform probability, from
its pool of choices -- no reciprocal pairing, and (unlike
``dock_rando.py``'s elevators/teleporters) no connectivity reject-and-retry
loop: a translator gate never removes a route, it only ever adds or removes
an item check on top of the vanilla graph shape, so the generator's own
fill-time accessibility sweep is exactly the same solvability safety net
door lock rando already relies on (see that module's docstring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..options import TranslatorGateRando
from .db_reader import GameDatabase, NodeId, load_game_database

if TYPE_CHECKING:
    from .. import MetroidPrime2World

# Matches randovania's ``LayoutTranslatorRequirement`` colors (vendored DB
# item short names -- see ``logic/item_mapping.py``'s ``DB_ITEM_TO_AP_ITEM``
# for Violet/Amber/Emerald/Cobalt -> "<Color> Translator").
TRANSLATOR_COLORS: tuple[str, ...] = ("Violet", "Amber", "Emerald", "Cobalt")

# One entry per configurable_node gate; ``None`` means "unlocked" (Scan
# Visor only, no translator required at all).
TranslatorGateAssignment = dict[NodeId, str | None]


def build_translator_gate_assignment(world: "MetroidPrime2World") -> TranslatorGateAssignment:
    """``{gate_node_id: color_or_None}`` for every one of the 17
    ``configurable_node`` translator gates, empty when ``translator_gate_rando``
    is left at "Vanilla" (its default) -- ``logic/regions.py``'s
    ``translator_gate_requirement`` then falls back to each gate's own
    vanilla color."""
    mode = world.options.translator_gate_rando.value
    if mode == TranslatorGateRando.option_vanilla:
        return {}

    choices: tuple[str | None, ...] = TRANSLATOR_COLORS
    if mode == TranslatorGateRando.option_full_random_unlocked:
        choices = (*TRANSLATOR_COLORS, None)

    db: GameDatabase = load_game_database()
    assignment: TranslatorGateAssignment = {}
    for node in db.all_nodes():
        if node.node_type != "configurable_node":
            continue
        assignment[node.id] = world.random.choice(choices)
    return assignment
