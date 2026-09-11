"""M2 tests: patch_data.py -- RandoConfiguration construction and
validation against the installed open-prime-rando package, plus
client/patcher_runner.py's dependency-free helpers (ISO version
detection, the goal-trigger context manager's wrap/unwrap behavior). See
PLAN.md sections H, I, J and K (M2).
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest

from .. import patch_data
from ..constants import LANDING_SITE_MREA, OPR_MODEL_NAMES, TEMPLE_GROUNDS_MLVL
from ..logic.db_reader import load_game_database
from .bases import MP2TestBase

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
        amounts = sorted(
            pickup["primary_stage"]["resources"][0]["amount"] for pickup in _all_pickups(self.config)
        )
        self.assertEqual(list(range(1, 120)), amounts)
        for pickup in _all_pickups(self.config):
            resources = pickup["primary_stage"]["resources"]
            self.assertEqual(1, len(resources))
            self.assertEqual(74, resources[0]["item"])
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
        self.assertTrue(hasattr(patcher_runner, "goal_trigger_installed"))
        self.assertTrue(hasattr(patcher_runner, "detect_iso_version"))
        del client

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_goal_trigger_installed_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import goal_trigger_installed

        original = opr_patcher.register_world_changes
        with goal_trigger_installed():
            self.assertIsNot(opr_patcher.register_world_changes, original)
        self.assertIs(opr_patcher.register_world_changes, original)

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_goal_trigger_installed_restores_even_on_exception(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import goal_trigger_installed

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError):
            with goal_trigger_installed():
                raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)
