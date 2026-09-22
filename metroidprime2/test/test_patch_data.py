"""M2 tests: patch_data.py -- RandoConfiguration construction and
validation against the installed open-prime-rando package, plus
client/patcher_runner.py's dependency-free helpers (ISO version
detection, the goal-trigger context manager's wrap/unwrap behavior). See
PLAN.md sections H, I, J and K (M2).
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
import zipfile

from BaseClasses import Item, ItemClassification
from Options import Visibility

from .. import patch_data
from ..constants import LANDING_SITE_MREA, OPR_MODEL_NAMES, PICKUP_COUNTER_ITEMS, TEMPLE_GROUNDS_MLVL
from ..items import ITEM_TABLE
from ..locations import LOCATION_TABLE
from ..logic.db_reader import load_game_database
from ..options import DisplayNonLocalItems, MetroidPrime2Options, RevealMapRemoved
from ..pickup_encoding import counter_and_amount
from .bases import MP2TestBase


def _other_game_item(game: str, name: str, player: int) -> Item:
    """A minimal fake item belonging to a different player/game, for
    exercising ``patch_data._pickup_appearance``'s cross-game model
    matching without needing a real second World instance. ``Item.game``
    is a plain class attribute (see ``BaseClasses.Item``), so a one-off
    subclass is the only way to fake a specific value for it."""
    cls = type("_OtherGameItem", (Item,), {"game": game})
    return cls(name, ItemClassification.progression, 999, player)

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None

_TRANSLATOR_COLORS = frozenset({"violet", "amber", "emerald", "cobalt"})

# The vanilla starting inventory (PLAN.md section F DEFAULT_STARTING_ITEMS
# / section H's "mandatory six"), by OPR PlayerItemEnum id.
_MANDATORY_STARTING_ITEM_IDS = (12, 8, 9, 0, 22, 15)


def _all_pickups(config: dict) -> list[dict]:
    pickups: list[dict] = []
    for world_change in config["world_changes"]:
        for area_change in world_change["area_changes"]:
            pickups.extend(area_change.get("pickups", []))
    return pickups


def _all_translator_gates(config: dict) -> list[dict]:
    gates: list[dict] = []
    for world_change in config["world_changes"]:
        for area_change in world_change["area_changes"]:
            gates.extend(area_change.get("translator_gates", []))
    return gates


class TestMakeRandoConfiguration(MP2TestBase):
    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            # MP2TestBase disables the WorldTestBase default reachability
            # tests (see bases.py), which world_setup() implements by
            # skipping construction entirely when one of those inherited
            # test methods is what's currently running; nothing below
            # needs self.world in that case.
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def test_119_pickups_across_5_mlvls(self) -> None:
        pickups = _all_pickups(self.config)
        self.assertEqual(119, len(pickups))
        self.assertEqual(5, len(self.config["world_changes"]))

    def test_pickup_indices_cover_0_to_118_exactly_once(self) -> None:
        # PLAN.md section P: each pickup grants one bit of one of
        # constants.PICKUP_COUNTER_ITEMS (pickup_encoding.counter_and_amount),
        # not an addend into a single shared counter -- so the generated
        # (item, amount) pairs must exactly match, as a set, what
        # counter_and_amount produces for every real pickup index.
        actual_pairs = sorted(
            (pickup["primary_stage"]["resources"][0]["item"], pickup["primary_stage"]["resources"][0]["amount"])
            for pickup in _all_pickups(self.config)
        )
        expected_pairs = sorted(counter_and_amount(index) for index in range(len(LOCATION_TABLE)))
        self.assertEqual(expected_pairs, actual_pairs)
        for pickup in _all_pickups(self.config):
            resources = pickup["primary_stage"]["resources"]
            self.assertEqual(1, len(resources))
            self.assertIn(resources[0]["item"], PICKUP_COUNTER_ITEMS)
            self.assertEqual([], pickup["progressive_stages"])

    def test_17_translator_gates(self) -> None:
        # "unlocked" (OPR's own no-translator-required TranslatorRequirement)
        # is a legal vanilla value, not just a translator_gate_rando "Random
        # (Unlocked)" outcome: randovania's prime2_opr starter preset ships
        # Temple Grounds/Hive Transport Area and Temple Grounds/Industrial
        # Site as "removed" (see data/vanilla_translator_gates.json and
        # logic/regions.py's translator_gate_requirement).
        gates = _all_translator_gates(self.config)
        self.assertEqual(17, len(gates))
        for gate in gates:
            self.assertIn(gate["translator"], (*_TRANSLATOR_COLORS, "unlocked"))
        self.assertEqual(2, sum(1 for gate in gates if gate["translator"] == "unlocked"))

    def test_9_translator_gates_have_holo_instance_overrides(self) -> None:
        # constants.TRANSLATOR_GATE_INSTANCE_OVERRIDES: 9 of the 17 gates'
        # vanilla rooms have ambiguous default OPR holo/glow instance names
        # (e.g. two objects both named "Glow For Holo 1"), so those 9 need a
        # disambiguating "holo1"/"holo2"/"conditional_relay" override in the
        # patcher-format dict or OPR's patcher raises MultipleInstances.
        gates = _all_translator_gates(self.config)
        self.assertEqual(9, sum(1 for gate in gates if "holo1" in gate))

    def test_every_model_data_is_a_known_opr_model(self) -> None:
        for pickup in _all_pickups(self.config):
            model = pickup["primary_stage"]["appearance"]["model_data"]
            self.assertIn(model, OPR_MODEL_NAMES)

    def test_mandatory_starting_items_present_at_capacity_one(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        for item_id in _MANDATORY_STARTING_ITEM_IDS:
            self.assertEqual(1, capacities.get(item_id), f"item {item_id} capacity")

    def test_varia_suit_capacity_is_never_more_than_one(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertEqual(1, capacities[12])

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        # Hard assertion (not a skip-if-invalid check): M2 explicitly
        # requires this to pass, with extra="forbid" so a typo'd/renamed
        # key would fail loudly instead of silently validating.
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_every_pickup_location_is_a_valid_pickup_modification(self) -> None:
        # Narrower than the whole-config validation above: directly
        # exercises PickupModification on each of the 119 pickups (PLAN.md
        # M2 test list).
        from open_prime_rando.echoes.pickups.schema import PickupModification

        for pickup in _all_pickups(self.config):
            PickupModification.model_validate(pickup)


class TestCrossGameItemModels(MP2TestBase):
    """M2 tests: ``_pickup_appearance``'s cross-game model matching
    (``display_nonlocal_items=match_game`` extended beyond same-game
    players -- see ``patch_data._CROSS_GAME_ITEM_NAMES``)."""

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.multiworld.player_name[2] = "OtherPlayer"
        # Any real pickup location belonging to this (player 1) world.
        self.location_name = LOCATION_TABLE[0].name

    def _appearance_for(self, item: Item) -> dict:
        location = self.multiworld.get_location(self.location_name, self.world.player)
        location.item = item
        return patch_data._pickup_appearance(self.world, self.location_name)

    def test_metroid_prime_energy_tank_matches(self) -> None:
        appearance = self._appearance_for(_other_game_item("Metroid Prime", "Energy Tank", 2))
        self.assertEqual(ITEM_TABLE["Energy Tank"].model, appearance["model_data"])

    def test_zero_mission_missile_tank_matches_missile_expansion(self) -> None:
        appearance = self._appearance_for(_other_game_item("Metroid: Zero Mission", "Missile Tank", 2))
        self.assertEqual(ITEM_TABLE["Missile Expansion"].model, appearance["model_data"])

    def test_fusion_power_bomb_tank_matches_power_bomb_expansion(self) -> None:
        appearance = self._appearance_for(_other_game_item("Metroid Fusion", "Power Bomb Tank", 2))
        self.assertEqual(ITEM_TABLE["Power Bomb Expansion"].model, appearance["model_data"])

    def test_super_metroid_missile_matches_missile_expansion(self) -> None:
        appearance = self._appearance_for(_other_game_item("Super Metroid", "Missile", 2))
        self.assertEqual(ITEM_TABLE["Missile Expansion"].model, appearance["model_data"])

    def test_super_metroid_grappling_beam_matches_grapple_beam(self) -> None:
        appearance = self._appearance_for(_other_game_item("Super Metroid", "Grappling Beam", 2))
        self.assertEqual(ITEM_TABLE["Grapple Beam"].model, appearance["model_data"])

    def test_gravity_suit_matches_gravity_boost_not_a_suit_model(self) -> None:
        # "Gravity Suit" (Metroid Prime/Zero Mission/Fusion/Super Metroid)
        # maps to our "Gravity Boost" -- a plain ability pickup, not a
        # suit-swap model like Varia/Dark/Light Suit.
        for game in ("Metroid Prime", "Metroid: Zero Mission", "Metroid Fusion", "Super Metroid"):
            with self.subTest(game=game):
                appearance = self._appearance_for(_other_game_item(game, "Gravity Suit", 2))
                self.assertEqual(ITEM_TABLE["Gravity Boost"].model, appearance["model_data"])

    def test_metroid_prime_missile_expansion_uses_prime1_reskin_override(self) -> None:
        # Experimental model override (patch_data._CROSS_GAME_MODEL_OVERRIDES)
        # -- Metroid Prime's own Missile Expansion gets the Prime-1-styled
        # model instead of our plain "MissileExpansion".
        appearance = self._appearance_for(_other_game_item("Metroid Prime", "Missile Expansion", 2))
        self.assertEqual("MissileExpansionPrime1", appearance["model_data"])

    def test_every_verified_and_experimental_entry_resolves_correctly(self) -> None:
        # Table-driven sweep: every (game, their name) -> our name mapping
        # actually round-trips through _pickup_appearance to the expected
        # model, including entries with a _CROSS_GAME_MODEL_OVERRIDES hit.
        for (game, their_name), our_name in patch_data._CROSS_GAME_ITEM_NAMES.items():
            with self.subTest(game=game, their_name=their_name):
                appearance = self._appearance_for(_other_game_item(game, their_name, 2))
                expected = patch_data._CROSS_GAME_MODEL_OVERRIDES.get((game, their_name), ITEM_TABLE[our_name].model)
                self.assertEqual(expected, appearance["model_data"])

    def test_unmatched_cross_game_item_falls_back(self) -> None:
        # Metroid Prime's "Ice Beam" has no Echoes equivalent.
        appearance = self._appearance_for(_other_game_item("Metroid Prime", "Ice Beam", 2))
        self.assertEqual(patch_data._FALLBACK_MODEL, appearance["model_data"])

    def test_unknown_game_falls_back(self) -> None:
        appearance = self._appearance_for(_other_game_item("Some Other Game", "Energy Tank", 2))
        self.assertEqual(patch_data._FALLBACK_MODEL, appearance["model_data"])

    def test_display_nonlocal_items_none_disables_cross_game_matching_too(self) -> None:
        self.world.options.display_nonlocal_items.value = DisplayNonLocalItems.option_none
        appearance = self._appearance_for(_other_game_item("Metroid Prime", "Energy Tank", 2))
        self.assertEqual(patch_data._FALLBACK_MODEL, appearance["model_data"])

    def test_varia_suit_never_matched_despite_identical_name_everywhere(self) -> None:
        # All four games happen to name this identically; our own
        # "VariaSuit" model crashes if placed anywhere but its single
        # vanilla location (see items.py), so this must never match.
        for game in ("Metroid Prime", "Metroid: Zero Mission", "Metroid Fusion"):
            with self.subTest(game=game):
                appearance = self._appearance_for(_other_game_item(game, "Varia Suit", 2))
                self.assertEqual(patch_data._FALLBACK_MODEL, appearance["model_data"])


class TestBeamConfigurationDefaults(MP2TestBase):
    def test_vanilla_costs_and_double_damage_actually_doubles(self) -> None:
        config = patch_data.make_rando_configuration(self.world)
        beams = config["beam_configuration"]
        for beam_name in ("dark", "light", "annihilator"):
            beam = beams[beam_name]
            self.assertEqual(1, beam["uncharged_cost"])
            self.assertEqual(5, beam["charged_cost"])
            self.assertEqual(5, beam["combo_missile_cost"])
            self.assertEqual(30, beam["combo_ammo_cost"])
        self.assertEqual(45, beams["dark"]["ammo_a"])
        self.assertIsNone(beams["dark"]["ammo_b"])
        self.assertEqual(46, beams["light"]["ammo_a"])
        self.assertIsNone(beams["light"]["ammo_b"])
        self.assertEqual(45, beams["annihilator"]["ammo_a"])
        self.assertEqual(46, beams["annihilator"]["ammo_b"])

        # Default (200%) must actually double, unlike open-prime-rando's
        # own internal default of 1.0/100% (a no-op) for this field.
        custom_items = config["custom_items"]
        self.assertEqual(2.0, custom_items["massive_damage_config"]["damage_increase_multiplier"])
        self.assertEqual(1, custom_items["massive_damage_config"]["max_count"])
        self.assertEqual(0.0, custom_items["defense_up_config"]["damage_reduction_multiplier"])
        self.assertEqual(1, custom_items["defense_up_config"]["max_count"])

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        config = patch_data.make_rando_configuration(self.world)
        RandoConfiguration.model_validate(config, extra="forbid")


class TestBeamConfigurationNonDefault(MP2TestBase):
    options = {
        "beam_ammo_costs": "free",
        "annihilator_ammo_source": "dark_only",
        "double_damage_multiplier": 300,
        "defense_up_damage_reduction": 25,
    }

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def test_free_beam_ammo_costs(self) -> None:
        beams = self.config["beam_configuration"]
        for beam_name in ("dark", "light", "annihilator"):
            beam = beams[beam_name]
            self.assertEqual(0, beam["uncharged_cost"])
            self.assertEqual(0, beam["charged_cost"])
            self.assertEqual(0, beam["combo_ammo_cost"])
            # Never 0 -- open-prime-rando requires combo_missile_cost >= 1.
            self.assertEqual(5, beam["combo_missile_cost"])

    def test_annihilator_dark_only_ammo_source(self) -> None:
        annihilator = self.config["beam_configuration"]["annihilator"]
        self.assertEqual(45, annihilator["ammo_a"])
        self.assertIsNone(annihilator["ammo_b"])
        # Dark/Light Beam's own ammo source is unaffected by this option.
        self.assertEqual(45, self.config["beam_configuration"]["dark"]["ammo_a"])
        self.assertEqual(46, self.config["beam_configuration"]["light"]["ammo_a"])

    def test_custom_item_multipliers(self) -> None:
        custom_items = self.config["custom_items"]
        self.assertEqual(3.0, custom_items["massive_damage_config"]["damage_increase_multiplier"])
        self.assertEqual(0.25, custom_items["defense_up_config"]["damage_reduction_multiplier"])
        # max_count is never exposed as an option -- both stay locked at 1
        # regardless (see _custom_items's docstring).
        self.assertEqual(1, custom_items["massive_damage_config"]["max_count"])
        self.assertEqual(1, custom_items["defense_up_config"]["max_count"])

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")


class TestMakeRandoConfigurationWithEntranceRando(MP2TestBase):
    """Door lock/elevator rando (logic/dock_rando.py) both enabled
    together: the generated config must still validate against the real
    open-prime-rando schema, and must actually carry non-empty
    door_locks/elevators entries reflecting the random assignment."""

    options = {"door_lock_rando": True, "elevator_rando": True}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def _all_door_locks(self) -> list[dict]:
        locks: list[dict] = []
        for world_change in self.config["world_changes"]:
            for area_change in world_change["area_changes"]:
                locks.extend(area_change.get("door_locks", []))
        return locks

    def _all_elevators(self) -> list[dict]:
        elevators: list[dict] = []
        for world_change in self.config["world_changes"]:
            for area_change in world_change["area_changes"]:
                elevators.extend(area_change.get("elevators", []))
        return elevators

    def test_door_locks_match_assignment_count(self) -> None:
        self.assertEqual(len(self.world.dock_rando.door_lock), len(self._all_door_locks()))

    def test_elevators_match_assignment_count(self) -> None:
        self.assertEqual(len(self.world.dock_rando.elevator), len(self._all_elevators()))

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")


class TestMakeRandoConfigurationWithPortalRando(MP2TestBase):
    """Portal rando (logic/dock_rando.py section E.3) enabled: the
    generated config must carry non-empty ``portals`` entries reflecting
    the random assignment, flip ``two_way_portals`` on, and still validate
    against the real open-prime-rando ``PortalChange``/``RandoConfiguration``
    schemas."""

    options = {"portal_rando": True}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def _all_portals(self) -> list[dict]:
        portals: list[dict] = []
        for world_change in self.config["world_changes"]:
            for area_change in world_change["area_changes"]:
                portals.extend(area_change.get("portals", []))
        return portals

    def test_two_way_portals_is_enabled(self) -> None:
        self.assertTrue(self.config["two_way_portals"])

    def test_portals_match_assignment_count(self) -> None:
        self.assertEqual(len(self.world.dock_rando.portal), len(self._all_portals()))
        self.assertEqual(66, len(self._all_portals()))

    def test_portal_fields_are_populated(self) -> None:
        for portal in self._all_portals():
            self.assertIsInstance(portal["source_dock_name"], str)
            self.assertIsInstance(portal["target_dock_name"], str)
            self.assertIsInstance(portal["target_mrea_id"], int)
            self.assertIsInstance(portal["portal_scan_destination"], str)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_portals_validate_against_installed_portal_change_schema(self) -> None:
        from open_prime_rando.echoes.portal import PortalChange

        for portal in self._all_portals():
            PortalChange.model_validate(portal)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")


class TestStartingAreaVanilla(MP2TestBase):
    """starting_room defaults to "vanilla" -- config.json's starting_area
    must still be exactly the vanilla Temple Grounds/Landing Site Save
    Station, matching origin_region_name (M0's TEMPLE_GROUNDS_MLVL /
    LANDING_SITE_MREA constants)."""

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def test_starting_area_is_landing_site(self) -> None:
        self.assertEqual(
            {"mlvl_id": TEMPLE_GROUNDS_MLVL, "mrea_id": LANDING_SITE_MREA},
            self.config["starting_area"],
        )

    def test_origin_region_name_is_landing_site_save_station(self) -> None:
        self.assertEqual("Temple Grounds/Landing Site/Save Station", self.world.origin_region_name)


class TestStartingAreaSaveStations(MP2TestBase):
    """starting_room="save_stations": config.json's starting_area must
    resolve to whichever of the 18 save-station candidates generate_early
    picked, and must still validate as a RandoConfiguration (M2's
    extra="forbid" shape: exactly {"mlvl_id": int, "mrea_id": int})."""

    options = {"starting_room": "save_stations"}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def test_chosen_node_is_a_save_station_candidate(self) -> None:
        db = load_game_database()
        self.assertIn(self.world.starting_location, db.starting_location_candidates("save_stations"))

    def test_starting_area_matches_chosen_node(self) -> None:
        db = load_game_database()
        node = db.node(self.world.starting_location)
        mlvl_id, mrea_id = patch_data._area_asset_ids(db, node)
        self.assertEqual({"mlvl_id": mlvl_id, "mrea_id": mrea_id}, self.config["starting_area"])

    def test_starting_area_shape(self) -> None:
        self.assertEqual({"mlvl_id", "mrea_id"}, self.config["starting_area"].keys())
        self.assertIsInstance(self.config["starting_area"]["mlvl_id"], int)
        self.assertIsInstance(self.config["starting_area"]["mrea_id"], int)

    def test_origin_region_name_matches_chosen_node(self) -> None:
        self.assertEqual(self.world.starting_location.ap_name, self.world.origin_region_name)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")


class TestStartingAreaAnywhere(MP2TestBase):
    """starting_room="anywhere": same shape/validation guarantees as
    TestStartingAreaSaveStations, but drawn from the full 272-room pool
    (which may have no save station of its own -- can_warp_to_start still
    covers it via the fixed 18-room set, see logic/regions.py)."""

    options = {"starting_room": "anywhere"}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        self.config = patch_data.make_rando_configuration(self.world)

    def test_chosen_node_is_an_anywhere_candidate(self) -> None:
        db = load_game_database()
        self.assertIn(self.world.starting_location, db.starting_location_candidates("anywhere"))

    def test_starting_area_matches_chosen_node(self) -> None:
        db = load_game_database()
        node = db.node(self.world.starting_location)
        mlvl_id, mrea_id = patch_data._area_asset_ids(db, node)
        self.assertEqual({"mlvl_id": mlvl_id, "mrea_id": mrea_id}, self.config["starting_area"])

    def test_origin_region_name_matches_chosen_node(self) -> None:
        self.assertEqual(self.world.starting_location.ap_name, self.world.origin_region_name)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_validates_against_installed_rando_configuration(self) -> None:
        from open_prime_rando.echoes.rando_configuration import RandoConfiguration

        RandoConfiguration.model_validate(self.config, extra="forbid")


class TestStartingAreaLightWorldOnly(MP2TestBase):
    """starting_room_light_world_only excludes every dark-region room from
    whichever pool starting_room selects."""

    options = {"starting_room": "anywhere", "starting_room_light_world_only": True}

    def test_chosen_node_is_in_a_light_region(self) -> None:
        db = load_game_database()
        _light_regions, dark_regions = db.light_dark_regions()
        self.assertNotIn(self.world.starting_location.region, dark_regions)


class TestStartingItemsWithPrecollectedMissileLauncher(MP2TestBase):
    # WorldTestBase's gen_steps stops at pre_fill; applying
    # options.start_inventory to precollected_items is normally done by
    # Main.py itself (the push_precollected loop right after
    # generate_early, in the full `python Generate.py`/`Main.py` pipeline),
    # so it's reproduced by hand in setUp for this unit test.
    options = {"start_inventory": {"Missile Launcher": 1}}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_missile_launcher_grants_id_73_and_44(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertEqual(1, capacities.get(73))
        self.assertEqual(5, capacities.get(44))


class TestStartingItemsWithPrecollectedMissileExpansionAndUnlockOption(MP2TestBase):
    """A precollected Missile Expansion (no Missile Launcher) writes
    capacity into id 44 via gains_for but never sets id 73 on its own; with
    missile_expansions_unlock_launcher on, starting_items_config must also
    set the launcher flag so the ISO's starting inventory is consistent
    with what the option grants in-game (PLAN.md section M)."""

    options = {
        "start_inventory": {"Missile Expansion": 1},
        "missile_expansions_unlock_launcher": True,
    }

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_launcher_flag_set_alongside_missile_capacity(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertEqual(5, capacities.get(44))
        self.assertEqual(1, capacities.get(73))


class TestStartingItemsWithPrecollectedMissileExpansionAndOptionOff(MP2TestBase):
    """Same precollected inventory as above, but with the option left at
    its default (off): the launcher flag must NOT be set, matching
    Randovania's behavior (an expansion alone grants no launcher)."""

    options = {"start_inventory": {"Missile Expansion": 1}}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_launcher_flag_not_set(self) -> None:
        # Behavior change (PLAN.md section M): a precollected expansion
        # alone, with the option off, used to leave capacity 44 at 5 (from
        # gains_for) while the launcher flag stayed unset -- unusable
        # in-game and a per-tick plan_grants warning. starting_items_config
        # now drops id 44 entirely in this case, matching what
        # compute_desired_capacities/logic would credit (0).
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertNotIn(44, capacities)
        self.assertNotIn(73, capacities)


class TestStartingItemsWithPrecollectedPowerBombExpansionAndUnlockOption(MP2TestBase):
    """Power Bomb counterpart of
    ``TestStartingItemsWithPrecollectedMissileExpansionAndUnlockOption``: a
    precollected Power Bomb Expansion (no main Power Bomb pickup) writes
    capacity into id 43 via gains_for; with
    power_bomb_expansions_unlock_power_bombs on, that capacity is left
    alone (there is no separate flag id to also set -- capacity 43 IS the
    unlock, PLAN.md section M)."""

    options = {
        "start_inventory": {"Power Bomb Expansion": 1},
        "power_bomb_expansions_unlock_power_bombs": True,
    }

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_capacity_kept_with_option_on(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertEqual(1, capacities.get(43))


class TestStartingItemsWithPrecollectedPowerBombExpansionAndOptionOff(MP2TestBase):
    """Same precollected inventory as above, but with the option left at
    its default (off): item 43 must be absent, matching what
    compute_desired_capacities/logic would credit (0) -- otherwise the ISO
    would start with a genuinely usable power bomb the option never
    intended to grant, and plan_grants would warn every tick (PLAN.md
    section M)."""

    options = {"start_inventory": {"Power Bomb Expansion": 1}}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_capacity_absent_with_option_off(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertNotIn(43, capacities)


class TestStartingItemsWithPrecollectedPowerBombMainAndOptionOff(MP2TestBase):
    """Main pickup + expansion precollected, option off: capacity is the
    full 2 (main) + 1 (expansion) = 3, unaffected by the subtractive fix
    above since the main pickup itself was precollected."""

    options = {"start_inventory": {"Power Bomb": 1, "Power Bomb Expansion": 1}}

    def setUp(self) -> None:
        super().setUp()
        if not self.constructed:
            return
        for item_name, count in self.world.options.start_inventory.value.items():
            for _ in range(count):
                self.multiworld.push_precollected(self.multiworld.create_item(item_name, self.player))
        self.config = patch_data.make_rando_configuration(self.world)

    def test_main_plus_expansion_capacity(self) -> None:
        capacities = {entry["item"]: entry["capacity"] for entry in self.config["starting_items"]}
        self.assertEqual(2 + 1, capacities.get(43))


class TestDetectIsoVersion(unittest.TestCase):
    def _write_fake_iso(self, header: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".iso")
        with os.fdopen(fd, "wb") as f:
            f.write(header.ljust(0x210, b"\x00"))
        self.addCleanup(os.remove, path)
        return path

    def test_ntsc_game_id(self) -> None:
        from ..client.patcher_runner import detect_iso_version

        self.assertEqual("NTSC", detect_iso_version(self._write_fake_iso(b"G2ME01")))

    def test_pal_game_id(self) -> None:
        from ..client.patcher_runner import detect_iso_version

        self.assertEqual("PAL", detect_iso_version(self._write_fake_iso(b"G2MP01")))

    def test_japanese_game_id_rejected(self) -> None:
        from ..client.patcher_runner import detect_iso_version

        with self.assertRaises(ValueError):
            detect_iso_version(self._write_fake_iso(b"G2MJ01"))

    def test_rvz_image_rejected(self) -> None:
        from ..client.patcher_runner import detect_iso_version

        with self.assertRaises(ValueError):
            detect_iso_version(self._write_fake_iso(b"RVZ\x01\x00\x00"))

    def test_unknown_game_id_rejected(self) -> None:
        from ..client.patcher_runner import detect_iso_version

        with self.assertRaises(ValueError):
            detect_iso_version(self._write_fake_iso(b"GM8E01"))


class TestPatcherRunnerDryImport(unittest.TestCase):
    def test_module_imports_without_open_prime_rando_at_call_time(self) -> None:
        # detect_iso_version and the module import itself must not require
        # open-prime-rando (every OPR/retro_data_structures import in
        # patcher_runner.py is deferred into function bodies -- PLAN.md
        # section I) -- this exercises that regardless of whether OPR
        # happens to be installed in this environment.
        from .. import client
        from ..client import patcher_runner

        self.assertTrue(hasattr(patcher_runner, "patch_iso_with_ap"))
        self.assertTrue(hasattr(patcher_runner, "detect_iso_version"))
        del client


class TestItemMapIconsAlwaysVisible(unittest.TestCase):
    """``item_map_icons_always_visible`` (client/patcher_runner.py):
    implements ``map_visibility``'s ``full_map_and_items`` value -- carried
    to the client as ``options.json``'s ``show_item_locations`` flag -- by
    explicitly setting every pickup map icon open-prime-rando adds to
    ``ObjectVisibility.AreaVisitOrMapStation``, matching open-prime-rando's
    own hardcoded default (PLAN.md section M; ``ObjectVisibility.Always``
    was tried first but is never used by any real upstream code path for
    any object type, so it was dropped as untested territory)."""

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_wraps_and_restores_add_map_icon(self) -> None:
        from open_prime_rando.echoes.pickups import pickup_editing

        from ..client.patcher_runner import item_map_icons_always_visible

        original = pickup_editing._add_map_icon
        with item_map_icons_always_visible():
            self.assertIsNot(pickup_editing._add_map_icon, original)
        self.assertIs(pickup_editing._add_map_icon, original)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes.pickups import pickup_editing

        from ..client.patcher_runner import item_map_icons_always_visible

        original = pickup_editing._add_map_icon
        with self.assertRaises(RuntimeError):
            with item_map_icons_always_visible():
                raise RuntimeError("boom")
        self.assertIs(pickup_editing._add_map_icon, original)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_forces_appended_mappable_objects_to_always_visible(self) -> None:
        # Exercises the real wrapper (not a reimplementation of it), against
        # a stub "original" _add_map_icon and a fake area/mapa, so this
        # doesn't need a real ISO/MREA to run. The stub reproduces the one
        # real side effect the wrapper depends on -- appending exactly one
        # MappableObject-shaped stand-in to area.mapa.mappable_objects --
        # and this asserts the *real* item_map_icons_always_visible code
        # (before/after length diffing, then setting visibility_mode) is
        # what turns that into ObjectVisibility.AreaVisitOrMapStation, not
        # a test double. The stub starts at ``Never`` so the assertion
        # proves the wrapper actively sets the value rather than leaving a
        # coincidentally-matching default untouched.
        from open_prime_rando.echoes.pickups import pickup_editing
        from retro_data_structures.formats.mapa import ObjectVisibility

        from ..client.patcher_runner import item_map_icons_always_visible

        class _FakeMappable:
            def __init__(self) -> None:
                self.visibility_mode = ObjectVisibility.Never

        class _FakeMapa:
            def __init__(self) -> None:
                self.mappable_objects: list[_FakeMappable] = []

        class _FakeArea:
            def __init__(self) -> None:
                self.mapa = _FakeMapa()

        area = _FakeArea()
        stub_calls = []

        def _stub_original_add_map_icon(editor, mlvl, area, instances) -> None:
            stub_calls.append((editor, mlvl, area, instances))
            area.mapa.mappable_objects.append(_FakeMappable())

        original = pickup_editing._add_map_icon
        pickup_editing._add_map_icon = _stub_original_add_map_icon
        try:
            with item_map_icons_always_visible():
                pickup_editing._add_map_icon("editor", "mlvl", area, "instances")
        finally:
            pickup_editing._add_map_icon = original

        self.assertEqual(1, len(stub_calls))
        self.assertEqual(1, len(area.mapa.mappable_objects))
        self.assertEqual(ObjectVisibility.AreaVisitOrMapStation, area.mapa.mappable_objects[0].visibility_mode)


class _MapVisibilityOptionTest(MP2TestBase):
    """Same rationale as test_warp_patch.py's ``_WarpToStartOptionTest``:
    show_item_locations is a patch-time setting with no home in OPR's
    RandoConfiguration (config.json is validated ``extra="forbid"``), so it
    has to travel in options.json instead -- which is exactly where
    ``patcher_runner.patch_iso_with_ap`` reads it back from.

    ``map_visibility`` (options.py) is a single Choice covering both flags
    at once, because an item dot needs its room drawn to be visible at all
    -- ``full_map_and_items`` implies ``reveal_map_at_start`` is also true.
    Each subclass below asserts the full pair for one Choice value."""

    expected_reveal_map_at_start: bool
    expected_show_item_locations: bool

    def _generate_container(self) -> tuple[dict[str, object], dict[str, object]]:
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            containers = list(pathlib.Path(output_directory).glob("*.apmp2"))
            self.assertEqual(len(containers), 1)
            with zipfile.ZipFile(containers[0]) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("show_item_locations", config)
        return options, config

    def test_flags_land_in_options_json_and_config_json(self) -> None:
        if type(self) is _MapVisibilityOptionTest:
            self.skipTest("base class")
        options, config = self._generate_container()
        self.assertEqual(options["show_item_locations"], self.expected_show_item_locations)
        self.assertEqual(
            config["map_visibility"]["reveal_map_at_start"], self.expected_reveal_map_at_start
        )


class TestMapVisibilityVanilla(_MapVisibilityOptionTest):
    options = {"map_visibility": "vanilla"}
    expected_reveal_map_at_start = False
    expected_show_item_locations = False


class TestMapVisibilityFullMap(_MapVisibilityOptionTest):
    options = {"map_visibility": "full_map"}
    expected_reveal_map_at_start = True
    expected_show_item_locations = False


class TestMapVisibilityFullMapAndItems(_MapVisibilityOptionTest):
    options = {"map_visibility": "full_map_and_items"}
    expected_reveal_map_at_start = True
    expected_show_item_locations = True


class TestRevealMapRemovedShim(unittest.TestCase):
    """``reveal_map`` (options.py) was folded into ``map_visibility``
    (PLAN.md section M), but the released 1.0.0 *did* ship it, so old YAMLs
    may still carry the key. ``RevealMapRemoved`` accepts the values that
    mean what ``map_visibility``'s ``vanilla`` default already means and
    raises, naming the replacement, for one that asked for a revealed map.

    Every case goes through ``from_any`` rather than the constructor,
    because that is the path a YAML value actually takes
    (``FreeText.from_any`` is ``cls(str(data))``, so YAML's ``false``
    arrives as the *truthy string* ``"False"`` -- the exact reason a plain
    ``Options.Removed`` is unusable here). Resolution goes through
    ``MetroidPrime2Options.type_hints``, the same ``typing.get_type_hints``
    lookup AP's own option loading uses, to prove the *dataclass field*
    really resolves to this class."""

    def test_reveal_map_field_is_the_shim(self) -> None:
        self.assertIs(MetroidPrime2Options.type_hints["reveal_map"], RevealMapRemoved)

    def test_field_is_hidden_from_option_uis(self) -> None:
        self.assertEqual(Visibility.none, MetroidPrime2Options.type_hints["reveal_map"].visibility)

    def test_requesting_a_revealed_map_raises_naming_the_replacement(self) -> None:
        reveal_map_option = MetroidPrime2Options.type_hints["reveal_map"]
        # Raises a bare Exception, matching Options.Removed's own shape.
        for value in (True, "true", 1):
            with self.subTest(value=value):
                with self.assertRaises(Exception) as caught:
                    reveal_map_option.from_any(value)
                self.assertIn("map_visibility", str(caught.exception))

    def test_declining_a_revealed_map_generates_normally(self) -> None:
        # `reveal_map: false` is what 1.0.0's own example_world_config.yaml
        # shipped, so this is the common case in copied YAMLs; it means
        # exactly what map_visibility's `vanilla` default means, so it must
        # not abort generation. "" is the absent-key default.
        reveal_map_option = MetroidPrime2Options.type_hints["reveal_map"]
        for value in (False, "false", 0, ""):
            with self.subTest(value=value):
                self.assertEqual("", reveal_map_option.from_any(value).value)


class TestRevealMapAbsentGeneratesFine(MP2TestBase):
    """Companion to TestRevealMapRemovedShim: a world with no `reveal_map`
    key at all (the normal case for every YAML written after this option
    was folded into `map_visibility`) must generate exactly like any other
    default-options world -- MP2TestBase.setUp() generating self.world
    without error is the assertion."""

    def test_world_generated(self) -> None:
        self.assertIsNotNone(self.world)
