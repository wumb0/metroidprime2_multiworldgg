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

That "only ever adds an item check" invariant holds for the 15 gates the
OPR-patched vanilla game actually raises. It does NOT hold for the two
randovania's prime2_opr starter preset ships as "removed" -- Temple
Grounds/Hive Transport Area and Temple Grounds/Industrial Site -- which is
why they are excluded from randomization here; see
``randomizable_gate_ids``.

The 22 translator lore holograms (``hint_scans.TRANSLATOR_LORE_HINT_SCANS``)
get the same treatment under ``translator_lore_rando``
(``build_translator_lore_assignment``), minus the "unlocked" outcome. A
hologram is a dead-end hint node, never a location or a route, so recoloring
one can't affect solvability at all -- ``logic/regions.py`` still applies
the reassigned color to the node's requirement so the graph matches the
patched game, and ``client/lore_translator_patch.py`` does the in-ISO half.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..hint_scans import TRANSLATOR_LORE_HINT_SCANS
from ..options import TranslatorGateRando, TranslatorLoreRando
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

# One entry per translator lore hologram whose color was reassigned, keyed by
# the hologram's STRG id (``HintScan.strg_id`` -- also the vendored DB hint
# node's ``extra.string_asset_id``). Holograms with no entry keep their
# vanilla color (``HintScan.translator``).
TranslatorLoreAssignment = dict[int, str]


def build_translator_gate_assignment(world: MetroidPrime2World) -> TranslatorGateAssignment:
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
    for node_id in randomizable_gate_ids(db):
        assignment[node_id] = world.random.choice(choices)
    return assignment


def randomizable_gate_ids(db: GameDatabase) -> list[NodeId]:
    """The ``configurable_node`` gates this world is allowed to reassign: the
    15 whose OPR-patched *vanilla* requirement is an actual translator color.

    The other two -- Temple Grounds/Hive Transport Area and Temple
    Grounds/Industrial Site -- are shipped "removed" (Unlocked) by
    randovania's own prime2_opr starter preset (see
    ``data/vanilla_translator_gates.json``), and putting a translator back
    on either one is not a difficulty knob, it is an unwinnable seed:
    open-prime-rando's always-on ``hive_access_tunnel_translator_gate``
    rebalance patch moves the Hive Access Tunnel gate onto the drop to Hive
    Chamber A, which leaves Landing Site -> Hive Access Tunnel -> Hive
    Transport Area -> Top of Elevator as the only item-free way out of the
    starting cluster (Landing Site's own Save Station -> Door to Service
    Access needs Space Jump/Bombs/Screw Attack, none of which are starting
    equipment). Colouring the Hive Transport Area gate closes that exit
    behind a translator whose every vanilla source sits on the far side of
    it, and the Industrial Site gate closes the very next room's exit the
    same way. Both were empirically fatal: every "Random" seed and most
    "Random (Unlocked)" seeds died with ``Fill.FillError`` until these two
    gates were pinned back to their vanilla "removed".
    """
    return [
        node.id
        for node in db.all_nodes()
        if node.node_type == "configurable_node" and db.vanilla_translator_gates[node.id] is not None
    ]


def build_translator_lore_assignment(world: MetroidPrime2World) -> TranslatorLoreAssignment:
    """``{strg_id: color}`` for every one of the 22 translator lore
    holograms, empty when ``translator_lore_rando`` is left at "Vanilla"
    (its default). The "Vanilla" branch makes no ``world.random`` draws, so
    leaving the option off keeps an existing seed's generation bit-for-bit
    unchanged."""
    if world.options.translator_lore_rando.value == TranslatorLoreRando.option_vanilla:
        return {}
    return {hint_scan.strg_id: world.random.choice(TRANSLATOR_COLORS) for hint_scan in TRANSLATOR_LORE_HINT_SCANS}
