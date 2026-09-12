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
key is absent): ``beam_configuration``, ``custom_items``,
``game_options_defaults``, ``suit_replacement``, ``hud_color``. The last
two are cosmetic, host.yaml-controlled settings applied client-side at
patch time (``client/patcher_runner.py``), not generation-time data.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from . import constants
from .items import ITEM_TABLE, gains_for
from .locations import LOCATION_TABLE
from .logic.db_reader import GameDatabase, Node, NodeId, load_game_database
from .options import DisplayNonLocalItems, MapVisibility, dark_damage_per_second

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
    """
    capacities: dict[int, int] = {}
    copy_index: dict[str, int] = {}

    for item in world.multiworld.precollected_items[world.player]:
        index = copy_index.get(item.name, 0)
        copy_index[item.name] = index + 1
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
        match_game = (
            item.game == constants.GAME_NAME
            and item.name in ITEM_TABLE
            and world.options.display_nonlocal_items.value == DisplayNonLocalItems.option_match_game
        )
        model = ITEM_TABLE[item.name].model if match_game else _FALLBACK_MODEL
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
    assert node.pickup_index is not None
    location_name = LOCATION_TABLE[node.pickup_index].name
    return {
        "location": _location_data_for(node),
        "primary_stage": {
            "resources": [{"item": constants.MAGIC_ITEM, "amount": node.pickup_index + 1}],
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
        "world_changes": _world_changes(world, db),
        "string_changes": [],
    }
