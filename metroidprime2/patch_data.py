"""Builds the open-prime-rando ``RandoConfiguration`` JSON for a single
player, from the already-generated ``World``/``MultiWorld`` (region graph,
item pool, and -- in real generation -- fill results). See PLAN.md section
H, and section K (M2) for the exact contents expected of the result.

Every value here must be plain JSON-able Python (``dict``/``list``/``str``/
``int``/``float``/``bool``/``None``) since ``__init__.py``'s
``generate_output`` just ``json.dumps`` the return value of
``make_rando_configuration`` verbatim into ``config.json``.

Deliberately NOT included here (left at open-prime-rando's own defaults,
which ``RandoConfiguration``'s pydantic model default-constructs when the
key is absent): ``game_options_defaults``, ``suit_replacement``,
``hud_color``. The last two are cosmetic, host.yaml-controlled settings
applied client-side at patch time (``client/patcher_runner.py``), not
generation-time data.

``beam_configuration`` (``beam_ammo_costs``/``annihilator_ammo_source``)
and ``custom_items`` (``double_damage_multiplier``/
``defense_up_damage_reduction``) ARE included, always explicitly -- see
``_beam_configuration``/``_custom_items`` below -- rather than left at
open-prime-rando's own pydantic defaults, because at least one of those
defaults is not vanilla-preserving (``MassiveDamageConfig.
damage_increase_multiplier`` defaults to 1.0, a no-op, not the real
double-damage value of 2.0)."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from . import constants
from .items import ITEM_TABLE, gains_for
from .locations import LOCATION_TABLE
from .logic.db_reader import GameDatabase, Node, NodeId, load_game_database
from .options import AnnihilatorAmmoSource, BeamAmmoCosts, DisplayNonLocalItems, MapVisibility, dark_damage_per_second
from .pickup_encoding import counter_and_amount

if TYPE_CHECKING:
    from . import MetroidPrime2World

# --------------------------------------------------------------------------
# Starting items
# --------------------------------------------------------------------------

# Mandatory regardless of options/precollected contents -- the vanilla
# Landing Site/Save Station starting inventory (PLAN.md section F
# DEFAULT_STARTING_ITEMS / section H). In normal generation these are
# already guaranteed to be present (item_pool.create_item_pool always
# pushes them via push_precollected, see PLAN.md section F), so this is
# purely a safety net: ``dict.setdefault`` below only fills a gap, it never
# double-counts on top of what precollected_items already contributed.
_MANDATORY_STARTING_ITEM_IDS: dict[int, int] = {
    0: 1,  # Power Beam
    22: 1,  # Charge Beam
    8: 1,  # Combat Visor
    9: 1,  # Scan Visor
    12: 1,  # Varia Suit
    15: 1,  # Morph Ball
}

# Varia Suit (item 12) doubles as open-prime-rando's "Defense Up" patch
# counter, whose max capacity defaults to 1 (PLAN.md Context fact / risk
# L7); giving it any other starting capacity would desync that counter, so
# this is enforced unconditionally rather than merely defaulted.
_VARIA_ITEM_ID = 12
_VARIA_STARTING_CAPACITY = 1

# Energy Tank capacity is nominally unbounded from gains_for's point of
# view (each copy just adds another (42, 1)), but the DOL's powerup_max
# table only allows so many; 14 matches ITEM_TABLE's own
# default_pool_count for Energy Tank (PLAN.md section F).
_ENERGY_TANK_ITEM_ID = 42
_ENERGY_TANK_MAX_STARTING_CAPACITY = 14

# Missile capacity / launcher-unlock flag ids (mirrors the same ids in
# client/receive_items.py's _MISSILE_ITEM/_MISSILE_LAUNCHER_FLAG). Needed
# here because a *precollected* Missile Expansion (e.g. via start_inventory)
# writes capacity into id 44 via gains_for but never sets id 73, so with
# missile_expansions_unlock_launcher on, the ISO itself would start
# inconsistent with the option's grant rule -- the client would have to
# correct it on the very first tick, and plan_grants logs a spurious
# "capacity is already above desired" warning when it does (PLAN.md section
# M).
_MISSILE_ITEM_ID = 44
_MISSILE_LAUNCHER_ITEM_ID = 73
# AP main-pickup item name, used (alongside _POWER_BOMB_MAIN_ITEM_NAME
# below) to tell "the main pickup itself was precollected" apart from
# "only expansions were precollected" -- gains_for accumulates capacity
# for either case identically, so the raw capacities dict can't
# distinguish them on its own.
_MISSILE_LAUNCHER_ITEM_NAME = "Missile Launcher"

# Power Bomb capacity id (OPR PlayerItemEnum slot 43) and the AP main
# pickup's item name (items.py:143, AP item id 21). Unlike missiles, there
# is no separate "unlocked" flag id to set here -- capacity id 43 is the
# *only* OPR resource Power Bombs have (PLAN.md section M: the whole gate
# lives in item_mapping's PowerBomb branch, not in the logic database) --
# so the fix below is purely subtractive: drop the capacity gains_for
# already wrote when neither the main pickup nor the unlock option would
# make it usable.
_POWER_BOMB_ITEM_ID = 43
_POWER_BOMB_MAIN_ITEM_NAME = "Power Bomb"


def starting_items_config(world: MetroidPrime2World) -> list[dict[str, int]]:
    """``[{"item": id, "capacity": n}, ...]`` for every precollected item
    (``multiworld.precollected_items[player]``), summing ``gains_for``
    across however many copies of each item were precollected -- the k-th
    copy of a progressive item (0-based) applies that item's k-th stage --
    plus the mandatory six, then clamps Varia Suit to exactly 1 and Energy
    Tank to at most 14 (PLAN.md section H).

    With ``missile_expansions_unlock_launcher`` on, also sets the Missile
    Launcher flag (id 73) if any missile capacity was precollected, so the
    ISO's starting inventory matches what the option grants in-game instead
    of relying on the client to fix it up on the first tick.

    **Behavior change:** ``gains_for`` writes ammo capacity for a
    precollected expansion regardless of whether its main item was also
    precollected, which used to mean ``start_inventory: {Missile Expansion:
    1}`` (or the Power Bomb equivalent) started the player with genuinely
    usable ammo the in-game grant/logic would never agree to on their own,
    and made ``plan_grants`` log a "capacity is already above desired"
    warning every tick once the client noticed the mismatch. So: when the
    relevant unlock option is off and the main pickup (``Missile Launcher``
    / ``Power Bomb``) was not itself precollected, the corresponding
    capacity (id 44 / id 43) is dropped entirely rather than left at
    whatever ``gains_for`` summed for expansions alone -- ``start_inventory``
    with only an expansion no longer starts you with usable ammo unless the
    corresponding unlock option is on. Power Bombs need this treatment
    unconditionally (there is no flag to compensate with); Missiles only
    need the subtractive half added here since the additive half (setting
    flag 73) already existed.
    """
    capacities: dict[int, int] = {}
    copy_index: dict[str, int] = {}
    has_missile_launcher = False
    has_power_bomb_main = False

    for item in world.multiworld.precollected_items[world.player]:
        index = copy_index.get(item.name, 0)
        copy_index[item.name] = index + 1
        if item.name == _MISSILE_LAUNCHER_ITEM_NAME:
            has_missile_launcher = True
        elif item.name == _POWER_BOMB_MAIN_ITEM_NAME:
            has_power_bomb_main = True
        if item.name not in ITEM_TABLE:
            # Not one of ours (e.g. a foreign item_link'd in some future
            # setup); nothing to grant in the ISO for it.
            continue
        for item_id, amount in gains_for(item.name, index):
            capacities[item_id] = capacities.get(item_id, 0) + amount

    for item_id, amount in _MANDATORY_STARTING_ITEM_IDS.items():
        capacities.setdefault(item_id, amount)

    capacities[_VARIA_ITEM_ID] = _VARIA_STARTING_CAPACITY
    if _ENERGY_TANK_ITEM_ID in capacities:
        capacities[_ENERGY_TANK_ITEM_ID] = min(
            capacities[_ENERGY_TANK_ITEM_ID], _ENERGY_TANK_MAX_STARTING_CAPACITY
        )

    if bool(world.options.missile_expansions_unlock_launcher) and capacities.get(
        _MISSILE_ITEM_ID, 0
    ) > 0:
        capacities.setdefault(_MISSILE_LAUNCHER_ITEM_ID, 1)
    elif not bool(world.options.missile_expansions_unlock_launcher) and not has_missile_launcher:
        # A precollected expansion alone would otherwise leave capacity 44
        # nonzero while the launcher flag stays 0 and logic credits no
        # missiles -- unusable in-game and a per-tick plan_grants warning.
        capacities.pop(_MISSILE_ITEM_ID, None)

    if (
        not bool(world.options.power_bomb_expansions_unlock_power_bombs)
        and not has_power_bomb_main
    ):
        # Same fix as missiles above, but Power Bombs have no flag to set
        # in the "option on" case -- capacity 43 IS the unlock, so nothing
        # needs to change there; only the off-and-unmain case needs
        # correcting.
        capacities.pop(_POWER_BOMB_ITEM_ID, None)

    return [{"item": item_id, "capacity": capacities[item_id]} for item_id in sorted(capacities)]


# --------------------------------------------------------------------------
# Pickup appearance (model/sound/jingle/hud_text/scan)
# --------------------------------------------------------------------------

# Sound/jingle constants, verbatim from
# randovania/games/prime2_opr/exporter/patch_data_factory.py
# (EchoesOPRPatchDataFactory.sound_data / .jingle_data) -- PLAN.md
# section H.
SOUND: dict[str, int] = {
    "standard": 10057,
    "expansion": 10057,
    "key": 1075,
}
JINGLE: dict[str, dict[str, Any]] = {
    "standard": {"file_name": "/audio/itm_x_long_00.dsp", "volume": 71},
    "expansion": {"file_name": "/audio/itm_x_short_00.dsp", "volume": 55},
    "key": {"file_name": "/audio/skytenkey-jin-short32.dsp", "volume": 110},
}

# Model name -> sound "kind", verbatim from the same file's
# ``_get_sound_type``.
_KEY_MODELS = frozenset({"SkyTempleKey", "DarkTempleKey", "EnergyTransferModule"})
_EXPANSION_MODELS = frozenset(
    {
        "MissileExpansion",
        "MissileExpansionLarge",
        "MissileExpansionPrime1",
        "PowerBombExpansion",
        "DarkBeamAmmoExpansion",
        "LightBeamAmmoExpansion",
        "BeamAmmoExpansion",
        "EnergyTank",
        "EnergyTankSmall",
    }
)

# Fallback model for anything not eligible for its "real" model (PLAN.md
# section H: "otherwise EnergyTransferModule"). Kept as a hook
# (MODEL_BY_CLASSIFICATION doesn't exist yet -- v1 has no need for it since
# every AP classification maps the same way -- but a future milestone that
# wants per-classification fallback models can add one without touching
# every call site).
_FALLBACK_MODEL = "EnergyTransferModule"

# --------------------------------------------------------------------------
# Cross-game item models (``display_nonlocal_items``): when a pickup
# belongs to a player of one of MultiWorldGG's other Metroid worlds
# (Metroid Prime, Metroid: Zero Mission, Metroid Fusion, Super Metroid --
# the only other Metroid games in this MultiWorldGG fork, see
# ``worlds/metroidprime``/``mzm``/``metroidfusion``/``sm``), and their AP
# item name is a straightforward conceptual match to one of ours,
# ``ITEM_TABLE``'s Echoes-appropriate model is used instead of the generic
# fallback. Keyed by (``item.game``, their AP item name) -> our AP item
# name (so the existing ``ITEM_TABLE[...].model`` lookup handles it
# identically to a same-game match).
#
# Deliberately excludes anything suit-related (``Varia Suit``, which all
# four games happen to name identically, included): our own "VariaSuit"
# model crashes the game when placed anywhere but its single vanilla
# location (see items.py's "Progressive Suit" entry), and that risk was
# never independently verified for other suit models either, so no suit
# name is matched here regardless of the other game -- see
# ``_UNSAFE_CROSS_GAME_MODELS`` below for the hard backstop. "Gravity
# Suit" is the one exception: it maps to our "Gravity Boost", which is
# architecturally a plain ability pickup here (`default_pool_count=1`,
# not in the "Suits" item group in items.py), not a suit-swap model, so it
# doesn't share Varia Suit's specific defect.
#
# Also deliberately excludes anything whose match is conceptually fuzzy
# (e.g. Metroid: Zero Mission's "Super Missile Tank" is a Super Missile
# *ammo* expansion, not our "Super Missile" beam-unlock item; Super
# Metroid's "Spring Ball"/"Reserve Tank"/"X-Ray Scope" and every game's
# other-element beams (Ice/Wave/Plasma/Spazer/...) have no Echoes
# equivalent at all) -- only names that mean the same thing in both games
# are included.
#
# Every entry below has been manually validated in-game (MT10) -- either
# because this world's OWN generation actually places the AP item at an
# arbitrary pickup location under some reachable option combination
# (nonzero pool count somewhere in item_pool.py, so the model is proven to
# work anywhere by our own seeds, the same standard "Progressive Suit"
# deliberately picked "DarkSuit" over "VariaSuit" to meet), or because MT10
# plando'd the model at a non-vanilla location and confirmed no crash for
# item names this world never places itself (Charge Beam, Morph Ball,
# Combat Visor, Scan Visor, Unlimited Missiles -- all mandatory starting
# items or never-placed useful items here, per items.py). If a player
# reports a crash tied to one of these, delete that one entry (falls back
# to the generic Energy Transfer Module) rather than reverting the whole
# feature.
_CROSS_GAME_ITEM_NAMES: dict[tuple[str, str], str] = {
    # Metroid Prime (MultiWorldGG/worlds/metroidprime, game = "Metroid Prime").
    ("Metroid Prime", "Energy Tank"): "Energy Tank",
    ("Metroid Prime", "Missile Expansion"): "Missile Expansion",
    ("Metroid Prime", "Power Bomb Expansion"): "Power Bomb Expansion",
    ("Metroid Prime", "Missile Launcher"): "Missile Launcher",
    ("Metroid Prime", "Power Bomb (Main)"): "Power Bomb",
    ("Metroid Prime", "Super Missile"): "Super Missile",
    ("Metroid Prime", "Grapple Beam"): "Grapple Beam",
    ("Metroid Prime", "Boost Ball"): "Boost Ball",
    ("Metroid Prime", "Spider Ball"): "Spider Ball",
    ("Metroid Prime", "Morph Ball Bomb"): "Morph Ball Bomb",
    ("Metroid Prime", "Space Jump Boots"): "Space Jump Boots",
    ("Metroid Prime", "Gravity Suit"): "Gravity Boost",
    # Metroid: Zero Mission (MultiWorldGG/worlds/mzm, game = "Metroid: Zero Mission").
    ("Metroid: Zero Mission", "Energy Tank"): "Energy Tank",
    ("Metroid: Zero Mission", "Missile Tank"): "Missile Expansion",
    ("Metroid: Zero Mission", "Power Bomb Tank"): "Power Bomb Expansion",
    ("Metroid: Zero Mission", "Bomb"): "Morph Ball Bomb",
    ("Metroid: Zero Mission", "Screw Attack"): "Screw Attack",
    ("Metroid: Zero Mission", "Space Jump"): "Space Jump Boots",
    ("Metroid: Zero Mission", "Gravity Suit"): "Gravity Boost",
    # Metroid Fusion (MultiWorldGG/worlds/metroidfusion, game = "Metroid Fusion").
    ("Metroid Fusion", "Energy Tank"): "Energy Tank",
    ("Metroid Fusion", "Missile Tank"): "Missile Expansion",
    ("Metroid Fusion", "Missile Data"): "Missile Launcher",
    ("Metroid Fusion", "Power Bomb Tank"): "Power Bomb Expansion",
    ("Metroid Fusion", "Power Bomb Data"): "Power Bomb",
    ("Metroid Fusion", "Bomb Data"): "Morph Ball Bomb",
    ("Metroid Fusion", "Screw Attack"): "Screw Attack",
    ("Metroid Fusion", "Space Jump"): "Space Jump Boots",
    ("Metroid Fusion", "Gravity Suit"): "Gravity Boost",
    # Super Metroid (MultiWorldGG/worlds/sm, game = "Super Metroid"). SM has
    # no separate missile/power-bomb "launcher"/ability item -- the first
    # copy of "Missile"/"Power Bomb" grants both the ability and capacity,
    # every copy after that just adds capacity -- so both map to our
    # *Expansion* items (the common case for most copies received).
    ("Super Metroid", "Energy Tank"): "Energy Tank",
    ("Super Metroid", "Missile"): "Missile Expansion",
    ("Super Metroid", "Power Bomb"): "Power Bomb Expansion",
    ("Super Metroid", "Super Missile"): "Super Missile",
    ("Super Metroid", "Grappling Beam"): "Grapple Beam",
    ("Super Metroid", "Screw Attack"): "Screw Attack",
    ("Super Metroid", "Space Jump"): "Space Jump Boots",
    ("Super Metroid", "Gravity Suit"): "Gravity Boost",
    # Powerup/ability models (Charge Beam, Morph Ball, Combat Visor, Scan
    # Visor, Unlimited Missiles) -- this world never places these itself,
    # but manual in-game validation (MT10) confirmed none of these models
    # crash.
    ("Metroid Prime", "Charge Beam"): "Charge Beam",
    ("Metroid Prime", "Morph Ball"): "Morph Ball",
    ("Metroid Prime", "Combat Visor"): "Combat Visor",
    ("Metroid Prime", "Scan Visor"): "Scan Visor",
    ("Metroid Prime", "Unlimited Missiles"): "Unlimited Missiles",
    ("Metroid: Zero Mission", "Charge Beam"): "Charge Beam",
    ("Metroid: Zero Mission", "Morph Ball"): "Morph Ball",
    ("Metroid Fusion", "Charge Beam"): "Charge Beam",
    ("Metroid Fusion", "Morph Ball"): "Morph Ball",
    ("Super Metroid", "Charge Beam"): "Charge Beam",
    ("Super Metroid", "Morph Ball"): "Morph Ball",
}

# Model overrides for specific cross-game matches where a source-game-
# specific reskin exists, applied on top of (and only when) the plain
# name match above already succeeded -- bypasses ITEM_TABLE's ordinary
# model for that one (game, their item name) pair.
#
# "MissileExpansionPrime1" (open-prime-rando's Missile Expansion model
# styled after Metroid Prime 1's) has been manually validated in-game
# (MT10) and renders properly. If Metroid Prime Missile Expansion pickups
# ever turn out to crash the game, delete this one entry (falls back to
# plain "MissileExpansion", not the generic fallback) rather than
# reverting cross-game matching entirely.
_CROSS_GAME_MODEL_OVERRIDES: dict[tuple[str, str], str] = {
    ("Metroid Prime", "Missile Expansion"): "MissileExpansionPrime1",
}

# Hard backstop, independent of what the tables above say: never resolve
# a cross-game match to one of these models. Currently just "VariaSuit"
# (see the comment above); kept as an explicit set rather than relying
# solely on the tables above being curated correctly.
_UNSAFE_CROSS_GAME_MODELS = frozenset({"VariaSuit"})

for _our_name in _CROSS_GAME_ITEM_NAMES.values():
    assert _our_name in ITEM_TABLE, f"_CROSS_GAME_ITEM_NAMES: {_our_name!r} is not an ITEM_TABLE entry"
    assert ITEM_TABLE[_our_name].model not in _UNSAFE_CROSS_GAME_MODELS, (
        f"_CROSS_GAME_ITEM_NAMES: {_our_name!r} resolves to an unsafe model"
    )
del _our_name  # pyright: ignore[reportPossiblyUnboundVariable]

for _game_and_name, _override_model in _CROSS_GAME_MODEL_OVERRIDES.items():
    assert _game_and_name in _CROSS_GAME_ITEM_NAMES, (
        f"_CROSS_GAME_MODEL_OVERRIDES: {_game_and_name!r} has no plain name match to override"
    )
    assert _override_model in constants.OPR_MODEL_NAMES, (
        f"_CROSS_GAME_MODEL_OVERRIDES: {_override_model!r} is not a known OPR model"
    )
    assert _override_model not in _UNSAFE_CROSS_GAME_MODELS, (
        f"_CROSS_GAME_MODEL_OVERRIDES: {_override_model!r} is an unsafe model"
    )
del _game_and_name, _override_model

# HUD memo text is deduplicated by open-prime-rando via the STRG name it
# derives from the text itself (PLAN.md Context facts), so keeping it short
# and free of characters that upset that string table is worth doing
# defensively even though AP item/player names are not attacker-controlled
# in the threat-model sense.
_HUD_TEXT_MAX_LENGTH = 60
_UNSAFE_TEXT_TRANSLATION = str.maketrans({"\n": " ", "\r": " ", "&": "", ";": ""})


def _sanitize(text: str, max_length: int | None = None) -> str:
    text = text.translate(_UNSAFE_TEXT_TRANSLATION)
    if max_length is not None:
        text = text[:max_length]
    return text


def _sound_kind(model_name: str) -> str:
    if model_name in _KEY_MODELS:
        return "key"
    if model_name in _EXPANSION_MODELS:
        return "expansion"
    return "standard"


def _pickup_appearance(world: MetroidPrime2World, location_name: str) -> dict[str, Any]:
    """``model_data``/``hud_text``/``scan`` for whatever item (if any) is
    currently placed at ``location_name`` (PLAN.md section H).

    ``item`` is ``None`` when this is called before ``fill`` has run (only
    possible in unit tests -- real generation always fills before
    ``generate_output``); that's treated the same as an off-world item with
    no match, i.e. the generic ETM fallback, so the resulting config is
    still fully valid JSON/schema-wise.

    A non-local item (belonging to another player) gets a matching model
    under ``display_nonlocal_items=match_game`` if it's either another
    Echoes player's item with the same AP item name, or another Metroid
    game's item with a conceptual match in ``_CROSS_GAME_ITEM_NAMES``;
    otherwise (including the option being off) it's the generic fallback.
    """
    location = world.multiworld.get_location(location_name, world.player)
    item = location.item

    if item is None:
        model = _FALLBACK_MODEL
        hud_text = "Nothing acquired!"
        scan = "Nothing."
    elif item.player == world.player:
        # Own item: always get their real model/name.
        model = ITEM_TABLE[item.name].model if item.name in ITEM_TABLE else _FALLBACK_MODEL
        hud_text = f"{item.name} acquired!"
        scan = f"{item.name}."
    else:
        recipient = world.multiworld.get_player_name(item.player)
        if item.game == constants.GAME_NAME:
            our_name = item.name if item.name in ITEM_TABLE else None
        else:
            our_name = _CROSS_GAME_ITEM_NAMES.get((item.game, item.name))

        model = _FALLBACK_MODEL
        if our_name is not None and world.options.display_nonlocal_items.value == DisplayNonLocalItems.option_match_game:
            candidate_model = _CROSS_GAME_MODEL_OVERRIDES.get((item.game, item.name), ITEM_TABLE[our_name].model)
            if candidate_model not in _UNSAFE_CROSS_GAME_MODELS:
                model = candidate_model

        hud_text = f"Sent {item.name} to {recipient}!"
        scan = f"{recipient}'s {item.name}."

    return {
        "model_data": model,
        "sound": SOUND[_sound_kind(model)],
        "jingle": JINGLE[_sound_kind(model)],
        "hud_text": _sanitize(hud_text, _HUD_TEXT_MAX_LENGTH),
        "scan": _sanitize(scan),
    }


# --------------------------------------------------------------------------
# Pickup location data (mirrors
# EchoesOPRPatchDataFactory._get_location_data)
# --------------------------------------------------------------------------


def _location_data_for(node: Node) -> dict[str, Any]:
    """Patcher-format ``location`` dict for a pickup node: the vendored
    ``extra.location_data`` verbatim, with ``instances`` flattened to the
    top level, ``state: "ZERO"`` added to every connection (both absent
    from our vendored copy of the randovania DB -- see PLAN.md section H),
    and (only for ``type: "custom"`` locations) a ``position`` derived from
    the node's logic-DB coordinates.
    """
    assert node.location_data is not None, f"{node.ap_name}: pickup node has no location_data"
    result: dict[str, Any] = copy.deepcopy(node.location_data)

    if "instances" in result:
        result.update(result.pop("instances"))

    for connection in result.get("connections", []):
        connection["state"] = "ZERO"

    if result.get("type") == "custom":
        coordinates = node.coordinates
        assert coordinates is not None, f"{node.ap_name}: custom pickup location has no coordinates"
        result["position"] = {
            "x": coordinates["x"],
            "y": coordinates["y"],
            "z": coordinates["z"],
        }

    return result


def _pickup_modification(world: MetroidPrime2World, node: Node) -> dict[str, Any]:
    """PLAN.md section P: each pickup grants exactly one bit (as an amount)
    of one of ``constants.PICKUP_COUNTER_ITEMS``, via
    ``pickup_encoding.counter_and_amount`` -- the single source of truth
    for the ``pickup_index -> (item, bit)`` layout, shared with
    ``client.py``'s decoder so generation time and runtime can never drift
    apart on it.
    """
    assert node.pickup_index is not None
    location_name = LOCATION_TABLE[node.pickup_index].name
    counter_item, bit_amount = counter_and_amount(node.pickup_index)
    return {
        "location": _location_data_for(node),
        "primary_stage": {
            "resources": [{"item": counter_item, "amount": bit_amount}],
            "appearance": _pickup_appearance(world, location_name),
            "conversion": [],
        },
        "progressive_stages": [],
    }


# --------------------------------------------------------------------------
# Translator gates
# --------------------------------------------------------------------------


def _door_lock_modification(db: GameDatabase, node: Node, new_weakness_name: str) -> dict[str, Any]:
    """``{"dock_name": ..., "old_door_type": ..., "new_door_type": ...}``
    for one door reassigned by ``logic/dock_rando.py``'s door lock rando.
    ``door_type`` strings are ``DockWeakness.door_type`` (vendored
    verbatim from the DB's ``extra.door_type``), which are exactly
    open-prime-rando's ``dock_lock_rando.dock_type_database.DOCK_TYPES``
    keys -- see PLAN.md Context."""
    assert node.dock_name is not None, f"{node.ap_name}: door node has no dock_name"
    assert node.default_dock_weakness is not None, f"{node.ap_name}: door node has no default_dock_weakness"
    old_weakness = db.dock_weaknesses[("door", node.default_dock_weakness)]
    new_weakness = db.dock_weaknesses[("door", new_weakness_name)]
    return {
        "dock_name": node.dock_name,
        "old_door_type": old_weakness.door_type,
        "new_door_type": new_weakness.door_type,
    }


def _elevator_modification(db: GameDatabase, node: Node, target_id: NodeId) -> dict[str, Any]:
    """``ElevatorChange``-shaped dict for one elevator reassigned by
    ``logic/dock_rando.py``. ``elevator_id`` is the
    ``WorldTeleporter`` script instance id (vendored as
    ``extra.teleporter_instance_id``); ``scan_strg`` is the vendored
    ``extra.scan_asset_id`` (None for the few dock nodes the randovania DB
    doesn't carry one for -- open-prime-rando leaves the scan text as-is
    in that case); ``target_name`` is the destination's region name, used
    in the elevator's "Access to <target_name> granted" scan text."""
    target_node = db.node(target_id)
    target_mlvl_id, target_mrea_id = _area_asset_ids(db, target_node)
    assert node.teleporter_instance_id is not None, f"{node.ap_name}: dock node has no teleporter_instance_id"
    return {
        "elevator_id": node.teleporter_instance_id,
        "target": {"mlvl_id": target_mlvl_id, "mrea_id": target_mrea_id},
        "scan_strg": node.scan_asset_id,
        "target_name": target_id.region,
    }


def _portal_modification(db: GameDatabase, node: Node, target_id: NodeId) -> dict[str, Any]:
    """``PortalChange``-shaped dict (open-prime-rando's
    ``echoes/portal.py::PortalChange``) for one portal reassigned by
    ``logic/dock_rando.py``'s portal rando. ``PortalChange`` has no
    ``target_mlvl_id`` sibling field -- "[a]ll portals must connect to a
    portal that connects back" within the same world file, since light/dark
    counterpart areas of one room always share an MLVL (PLAN.md Context /
    ``db_reader.GameDatabase.mlvl_for_region``) -- so only the target's MREA
    id is needed; the assertion below is a cheap sanity check on that
    assumption, not a real branch."""
    target_node = db.node(target_id)
    assert node.dock_name is not None, f"{node.ap_name}: portal node has no dock_name"
    assert target_node.dock_name is not None, f"{target_id.ap_name}: portal target has no dock_name"
    mlvl_id, _mrea_id = _area_asset_ids(db, node)
    target_mlvl_id, target_mrea_id = _area_asset_ids(db, target_node)
    assert mlvl_id == target_mlvl_id, (
        f"{node.ap_name}: portal target {target_id.ap_name} is in a different MLVL "
        f"({target_mlvl_id} != {mlvl_id})"
    )
    return {
        "source_dock_name": node.dock_name,
        "target_mrea_id": target_mrea_id,
        "target_dock_name": target_node.dock_name,
        "portal_scan_destination": target_id.area,
    }


def _translator_gate_modification(world: MetroidPrime2World, node: Node) -> dict[str, Any]:
    """``{"translator": <color-or-"unlocked">, ...}`` for one of the 17
    ``configurable_node`` translator gates: the gate's vanilla required
    color (``db.vanilla_translator_gates``, vendored from randovania's own
    prime2_opr starter preset -- ``None``/"unlocked" for the two gates that
    preset ships as "removed", see ``logic/regions.py``'s
    ``translator_gate_requirement``), unless ``translator_gate_rando``
    reassigned it (see
    ``logic/translator_gate_rando.py`` -- the same
    ``world.translator_gate_assignment`` dict ``logic/regions.py``'s
    ``translator_gate_requirement`` reads, so the in-ISO gate and the logic
    graph can never disagree). open-prime-rando's own "unlocked"
    ``TranslatorRequirement`` (``open_prime_rando.echoes.translator_gates``)
    is exactly the in-ISO counterpart of the ``None`` ("no translator
    required") entries "Random (Unlocked)" mode can produce.

    Randovania's exporter also spreads ``node.extra["gate_instances"]`` into
    this dict to override OPR's default hologram/glow/relay instance name
    lookups (``create_translator_gates`` in
    ``randovania/games/prime2_opr/exporter/patch_data_factory.py``) for
    gates whose vanilla room has an ambiguous default name (e.g. two
    objects both literally named "Glow For Holo 1" -- OPR's name lookup
    then raises ``MultipleInstances`` instead of patching). Our vendored DB
    (data/logic_database/, sync'd from randovania's ``prime2`` logic
    database) has no ``gate_instances`` field at all -- that's specific to
    randovania's OPR-targeting ``prime2_opr`` game definition -- so
    ``constants.TRANSLATOR_GATE_INSTANCE_OVERRIDES`` hand-copies the same 9
    gates' override data from there, keyed by ``gate_index`` instead of by
    node extra.
    """
    if node.id in world.translator_gate_assignment:
        color = world.translator_gate_assignment[node.id]
    else:
        db = load_game_database()
        assert node.id in db.vanilla_translator_gates, f"{node.ap_name}: no vanilla translator requirement"
        color = db.vanilla_translator_gates[node.id]
    result: dict[str, Any] = {"translator": color.lower() if color is not None else "unlocked"}
    if node.gate_index is not None and node.gate_index in constants.TRANSLATOR_GATE_INSTANCE_OVERRIDES:
        result.update(constants.TRANSLATOR_GATE_INSTANCE_OVERRIDES[node.gate_index])
    return result


# --------------------------------------------------------------------------
# World/area change grouping
# --------------------------------------------------------------------------


def _area_asset_ids(db: GameDatabase, node: Node) -> tuple[int, int]:
    region = db.regions[node.id.region]
    area = region.areas[node.id.area]
    mlvl_id = db.mlvl_for_region(node.id.region)
    assert area.asset_id is not None, f"{node.ap_name}: area has no MREA asset_id"
    return mlvl_id, area.asset_id


def _world_changes(world: MetroidPrime2World, db: GameDatabase) -> list[dict[str, Any]]:
    area_changes: dict[tuple[int, int], dict[str, Any]] = {}

    def area_change_for(mlvl_id: int, mrea_id: int) -> dict[str, Any]:
        return area_changes.setdefault((mlvl_id, mrea_id), {"mrea_id": mrea_id})

    for node in db.pickup_nodes():
        mlvl_id, mrea_id = _area_asset_ids(db, node)
        change = area_change_for(mlvl_id, mrea_id)
        change.setdefault("pickups", []).append(_pickup_modification(world, node))

    for node in db.all_nodes():
        if node.node_type != "configurable_node":
            continue
        mlvl_id, mrea_id = _area_asset_ids(db, node)
        change = area_change_for(mlvl_id, mrea_id)
        change.setdefault("translator_gates", []).append(_translator_gate_modification(world, node))

    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != "door":
            continue
        new_name = world.dock_rando.door_lock.get(node.id)
        if new_name is None:
            continue
        mlvl_id, mrea_id = _area_asset_ids(db, node)
        change = area_change_for(mlvl_id, mrea_id)
        change.setdefault("door_locks", []).append(_door_lock_modification(db, node, new_name))

    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != "elevator":
            continue
        target_id = world.dock_rando.elevator.get(node.id)
        if target_id is None:
            continue
        mlvl_id, mrea_id = _area_asset_ids(db, node)
        change = area_change_for(mlvl_id, mrea_id)
        change.setdefault("elevators", []).append(_elevator_modification(db, node, target_id))

    for node in db.all_nodes():
        if node.node_type != "dock" or node.dock_type != "portal":
            continue
        target_id = world.dock_rando.portal.get(node.id)
        if target_id is None:
            continue
        mlvl_id, mrea_id = _area_asset_ids(db, node)
        change = area_change_for(mlvl_id, mrea_id)
        change.setdefault("portals", []).append(_portal_modification(db, node, target_id))

    by_mlvl: dict[int, list[dict[str, Any]]] = {}
    for (mlvl_id, _mrea_id), change in area_changes.items():
        by_mlvl.setdefault(mlvl_id, []).append(change)

    return [{"mlvl_id": mlvl_id, "area_changes": changes} for mlvl_id, changes in by_mlvl.items()]


# --------------------------------------------------------------------------
# Beam ammo costs / Annihilator ammo source (beam_configuration)
# --------------------------------------------------------------------------

# PlayerItemEnum.DarkAmmo/LightAmmo (retro_data_structures.enums.echoes),
# matching the item ids used everywhere else in this world (items.py,
# client/receive_items.py, logic/item_mapping.py).
_DARK_AMMO_ID = 45
_LIGHT_AMMO_ID = 46

# (uncharged_cost, charged_cost, combo_missile_cost, combo_ammo_cost) --
# open-prime-rando's ``BeamAmmoConfiguration`` fields, identical across
# Dark/Light/Annihilator in vanilla. combo_missile_cost is left at its
# vanilla value even for "free": open-prime-rando requires it >= 1 (it's a
# missile cost, not a beam-ammo cost).
_BEAM_AMMO_COST_PRESETS: dict[int, tuple[int, int, int, int]] = {
    BeamAmmoCosts.option_vanilla: (1, 5, 5, 30),
    BeamAmmoCosts.option_cheap: (1, 3, 5, 15),
    BeamAmmoCosts.option_expensive: (2, 10, 5, 60),
    BeamAmmoCosts.option_free: (0, 0, 5, 0),
}

_ANNIHILATOR_AMMO_SOURCES: dict[int, tuple[int, int | None]] = {
    AnnihilatorAmmoSource.option_both: (_DARK_AMMO_ID, _LIGHT_AMMO_ID),
    AnnihilatorAmmoSource.option_dark_only: (_DARK_AMMO_ID, None),
    AnnihilatorAmmoSource.option_light_only: (_LIGHT_AMMO_ID, None),
}


def _beam_ammo_config(ammo_a: int | None, ammo_b: int | None, costs: tuple[int, int, int, int]) -> dict[str, Any]:
    uncharged_cost, charged_cost, combo_missile_cost, combo_ammo_cost = costs
    return {
        "ammo_a": ammo_a,
        "ammo_b": ammo_b,
        "uncharged_cost": uncharged_cost,
        "charged_cost": charged_cost,
        "combo_missile_cost": combo_missile_cost,
        "combo_ammo_cost": combo_ammo_cost,
    }


def _beam_configuration(world: MetroidPrime2World) -> dict[str, Any]:
    """open-prime-rando ``BeamConfiguration`` -- costs for
    ``beam_ammo_costs``, ammo source remapping for
    ``annihilator_ammo_source``. ``power`` is left unspecified (it has no
    ammo cost in vanilla or here; open-prime-rando's own field default
    applies)."""
    costs = _BEAM_AMMO_COST_PRESETS[world.options.beam_ammo_costs.value]
    ammo_a, ammo_b = _ANNIHILATOR_AMMO_SOURCES[world.options.annihilator_ammo_source.value]
    return {
        "dark": _beam_ammo_config(_DARK_AMMO_ID, None, costs),
        "light": _beam_ammo_config(_LIGHT_AMMO_ID, None, costs),
        "annihilator": _beam_ammo_config(ammo_a, ammo_b, costs),
    }


# --------------------------------------------------------------------------
# Custom items (Double Damage / Defense Up)
# --------------------------------------------------------------------------


def _custom_items(world: MetroidPrime2World) -> dict[str, Any]:
    """open-prime-rando ``CustomItemsConfig``. ``max_count`` is always 1
    for both -- Defense Up's counter is the Varia Suit inventory slot,
    whose capacity this world always locks at exactly 1 (see
    ``client/receive_items.py``); Double Damage is never granted more than
    once by the generic gains loop either way (see ``items.py``'s entry),
    so raising it would have no observable effect."""
    return {
        "massive_damage_config": {
            "damage_increase_multiplier": world.options.double_damage_multiplier.value / 100,
            "max_count": 1,
        },
        "defense_up_config": {
            "damage_reduction_multiplier": world.options.defense_up_damage_reduction.value / 100,
            "max_count": 1,
        },
    }


# --------------------------------------------------------------------------
# Top level
# --------------------------------------------------------------------------

_GAME_TITLE_MAX_LENGTH = 64
_SEED_NAME_PREFIX_LENGTH = 10


def make_rando_configuration(world: MetroidPrime2World) -> dict[str, Any]:
    """The full open-prime-rando ``RandoConfiguration`` JSON for
    ``world``, minus the client-time cosmetic overrides (``hud_color``,
    ``suit_replacement`` -- applied by ``client/patcher_runner.py`` from
    host.yaml settings at patch time). See PLAN.md section H.
    """
    db = load_game_database()
    multiworld = world.multiworld

    seed_name_prefix = multiworld.seed_name[:_SEED_NAME_PREFIX_LENGTH]
    game_title = f"MWGG Echoes {seed_name_prefix} P{world.player}"[:_GAME_TITLE_MAX_LENGTH]

    dark_aether_damage = dark_damage_per_second(world.options.dark_aether_damage.value)
    dark_suit_damage = dark_damage_per_second(world.options.dark_suit_damage.value)

    starting_mlvl_id, starting_mrea_id = _area_asset_ids(db, db.node(world.starting_location))

    return {
        "game_title": game_title,
        "title_screen_text": f"\nMultiworldGG - {world.player_name}",
        "seed": world.random.getrandbits(31),
        "world_uuid": world.world_uuid,
        "starting_area": {
            "mlvl_id": starting_mlvl_id,
            "mrea_id": starting_mrea_id,
        },
        "starting_items": starting_items_config(world),
        "map_visibility": {
            "reveal_map_at_start": world.options.map_visibility.value != MapVisibility.option_vanilla,
            "unvisited_room_names": bool(world.options.unvisited_room_names.value),
            "areas_to_never_reveal": [],
            "unvisited_map_icons": False,
        },
        "practice_mod": "disabled",
        "auto_enabled_elevators": False,
        "two_way_portals": bool(world.options.portal_rando),
        "inverted_mode": False,
        "damage_changes": {
            "energy_per_tank": int(world.options.energy_per_tank.value),
            "safe_zone_heal_per_second": 1.0,
            "dangerous_energy_tanks": bool(world.options.dangerous_energy_tanks.value),
            "dark_world_damage": dark_aether_damage,
            "dark_suit_protection": dark_suit_damage / dark_aether_damage,
        },
        "beam_configuration": _beam_configuration(world),
        "custom_items": _custom_items(world),
        "world_changes": _world_changes(world, db),
        "string_changes": [],
    }
