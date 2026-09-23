"""M1 tests: logic/regions.py -- the generated region/entrance graph. See
``PLAN.md`` sections E and K (M1).
"""

from __future__ import annotations

import re
import unittest

from BaseClasses import CollectionState

from ..items import ITEM_TABLE
from ..locations import LOCATION_TABLE
from ..logic.db_reader import Node, NodeId, load_game_database
from ..logic.regions import can_warp_to_start
from .bases import MP2TestBase

# "Pickup (X)" or "Pickup 2 (X)" -> X.
_PICKUP_NAME_RE = re.compile(r"^Pickup(?: \d+)? \((.+)\)$")


def _vanilla_item_name(node: Node) -> str:
    """The vanilla AP item for a pickup node, derived from its node name
    (PLAN.md section K, M1 "vanilla-placement test"), with
    ``extra.location_data.original_model`` (``node.location_data``) as the
    tie-breaker wherever the node-name convention is ambiguous or wrong.

    Four "Pickup (Dark Ammo)" nodes (Agon Wastes/Central Mining Station,
    Dark Torvus Bog/Cache A, Sky Temple Grounds/Profane Path, Sanctuary
    Fortress/Watch Station -- pickup indices 40/65/17/105) all have
    ``original_model == "BeamAmmoExpansion"``, not a plain Dark Ammo
    Expansion: their vanilla item grants both Dark and Light ammo at once.
    Verified empirically -- without this fix, the vanilla-placement sweep
    stalls (Amorbis is unwinnable with only the baseline 50 Light ammo from
    the Light Beam itself, needing >=60), confirming this is the real
    vanilla item at these four locations, not the "Dark Ammo Expansion"
    the bare node-name heuristic would guess.
    """
    match = _PICKUP_NAME_RE.match(node.id.node)
    assert match, f"unexpected pickup node name: {node.id.node!r}"
    label = match.group(1)
    original_model = (node.location_data or {}).get("original_model")

    if label == "Missile":
        return "Missile Expansion"
    if label == "Power Bomb":
        # Only pickup_index 88 is the main Power Bomb launcher; every other
        # "Pickup (Power Bomb)" node is an expansion.
        return "Power Bomb" if node.pickup_index == 88 else "Power Bomb Expansion"
    if label == "Dark Ammo":
        if original_model == "BeamAmmoExpansion":
            return "Beam Ammo Expansion"
        return "Dark Ammo Expansion"
    if label == "Light Ammo":
        if original_model == "BeamAmmoExpansion":
            return "Beam Ammo Expansion"
        return "Light Ammo Expansion"
    if label == "Energy Transfer Module":
        return "Missile Expansion"
    if label == "Missile On Ship":
        # Temple Grounds/GFMC Compound's "Pickup 2 (Missile On Ship)" node;
        # extra.location_data.original_model is "MissileExpansion" (verified
        # in the vendored logic database), i.e. a plain Missile Expansion
        # under an unusual node name.
        return "Missile Expansion"
    return label


class TestAllLocationsReachableWithEverything(MP2TestBase):
    def test_all_119_locations_reachable(self) -> None:
        self.collect_all_but([])
        for location in LOCATION_TABLE:
            with self.subTest(location=location.name):
                self.assertTrue(self.can_reach_location(location.name))

    def test_game_beatable_with_everything(self) -> None:
        self.collect_all_but([])
        self.assertTrue(self.multiworld.can_beat_game(self.multiworld.state))


class TestNegativeReachability(MP2TestBase):
    """A handful of deep, item-gated locations that should NOT be reachable
    with only the vanilla starting inventory (no pool items collected).
    Verified empirically against the vendored logic database: with a fresh
    CollectionState (containing only push_precollected items),
    state.update_reachable_regions never leaves the Temple Grounds' Hive
    Chamber/Landing Site/Industrial Site cluster, so no pickup location
    anywhere -- these three included -- is reachable yet."""

    def test_deep_key_locations_unreachable_at_start(self) -> None:
        for index, name in (
            (15, "Sky Temple Grounds: Accursed Lake - Pickup (Sky Temple Key 9)"),
            (69, "Dark Torvus Bog: Venomous Pond - Pickup (Dark Torvus Key 3)"),
            (100, "Ing Hive: Culling Chamber - Pickup (Ing Hive Key 1)"),
        ):
            with self.subTest(location=name):
                self.assertEqual(name, LOCATION_TABLE[index].name)
                self.assertFalse(self.can_reach_location(name))


# Great Temple/Temple Sanctuary's "Transport A Translator Gate" (Emerald).
# See VANILLA_PLACEMENT_BOOTSTRAP_ITEM below.
_TRANSPORT_A_GATE = NodeId("Great Temple", "Temple Sanctuary", "Transport A Translator Gate")

# The one item a *vanilla* item layout cannot bootstrap on the OPR-patched
# game, and why:
#
# open-prime-rando always applies ``specific_area_patches.rebalance_patches.
# temple_sanctuary_emerald_gate`` ("Keep the Emerald gate active from the
# beginning"), which leaves Great Temple/Temple Sanctuary's Transport A
# Emerald translator gate up from the moment the game starts. Retail Echoes
# instead only raises that gate after the Alpha Splinter fight, which
# randovania's plain ``prime2`` logic database modelled with an
# "Event - Transport A Gate Removal" event node (Event91) plus the
# ``VanillaGreatTempleEmeraldGate`` misc resource; ``prime2_opr`` deletes
# that node outright, so Temple Sanctuary's Room Center is reachable only
# *through* one of the three translator gates.
#
# With vanilla placement that is a genuine hard lock, not a logic bug: the
# only exits from the starting Landing Site/Hive/Industrial Site/Agon
# cluster into the rest of the game are the Great Temple Transport A gate
# (Emerald), the GFMC Compound gate (Emerald), Temple Assembly Site ->
# Temple Transport B (Violet), and Service Access -> Meeting Grounds (a
# Super Missile blast shield) -- and vanilla puts Emerald Translator in
# Torvus Bog/Torvus Energy Controller, Violet Translator in Great
# Temple/Main Energy Controller, and Super Missile in Torvus Bog/Torvus
# Temple, i.e. all three behind that same wall.
#
# Granting exactly this one item restores the retail game's own "the
# Transport A gate isn't up yet" head start, and nothing else: with it the
# vanilla layout reaches all 119 pickups and the victory event again
# (verified -- it is the *only* item that has to be added).
VANILLA_PLACEMENT_BOOTSTRAP_ITEM = "Emerald Translator"


class TestVanillaPlacement(MP2TestBase):
    """Lock the vanilla item onto every one of the 119 pickup locations
    (derived from each pickup node's own name) and check the game is still
    beatable -- i.e. the vendored vanilla game itself satisfies our own
    compiled logic -- given the single
    ``VANILLA_PLACEMENT_BOOTSTRAP_ITEM`` head start open-prime-rando's
    always-on Great Temple Emerald gate rebalance patch makes mandatory
    (see that constant for the full derivation)."""

    # trick_level left at its "disabled" default (every trick off), matching
    # randovania's starter preset: vanilla placement is beatable with no
    # tricks at all once dock locks use correct front-blast-back-free-unlock
    # semantics (see logic/regions.py). The previous "expert" override here
    # was a workaround for a dock-lock translation bug (an incorrect
    # "back_lock" conjunct that required blasting *both* sides of a locked
    # door, when randovania only ever requires the front side, with the
    # back falling open for free once reached) -- now fixed.
    options = {
        "progressive_suit": False,
        "progressive_grapple": False,
        "sky_temple_keys": 9,
    }

    def test_vanilla_item_names_resolve(self) -> None:
        # Every derived vanilla item name must be a real ITEM_TABLE entry
        # (sanity check on _vanilla_item_name before using it below).
        db = load_game_database()
        for node in db.pickup_nodes():
            name = _vanilla_item_name(node)
            with self.subTest(pickup_index=node.pickup_index, node=node.id.node):
                self.assertIn(name, ITEM_TABLE)

    def test_vanilla_placement_is_beatable(self) -> None:
        db = load_game_database()
        for node in db.pickup_nodes():
            item_name = _vanilla_item_name(node)
            assert node.pickup_index is not None, f"{node.ap_name}: pickup node has no pickup_index"
            location_name = LOCATION_TABLE[node.pickup_index].name
            location = self.multiworld.get_location(location_name, self.player)
            location.place_locked_item(self.world.create_item(item_name))

        state = CollectionState(self.multiworld)
        # Sanity-check the premise of VANILLA_PLACEMENT_BOOTSTRAP_ITEM: the
        # gate this compensates for really is the vanilla Emerald gate. If
        # randovania/OPR ever restore the retail "gate removal" behaviour,
        # this is the line that should be revisited first.
        self.assertEqual(db.vanilla_translator_gates[_TRANSPORT_A_GATE], "Emerald")
        state.collect(
            self.world.create_item(VANILLA_PLACEMENT_BOOTSTRAP_ITEM), prevent_sweep=True
        )
        # A full fixed-point sweep (matching what can_beat_game() itself
        # does internally) must actually reach every one of the 119
        # pickups and the victory event, not just "some locked items
        # exist" -- can_beat_game() alone would also pass trivially if the
        # sweep stalled immediately, since has_beaten_game() is only
        # checked after each sphere.
        for _ in state.sweep_for_advancements(yield_each_sweep=True):
            pass
        pickup_locations = list(LOCATION_TABLE)
        for loc in pickup_locations:
            with self.subTest(location=loc.name):
                self.assertIn(
                    self.multiworld.get_location(loc.name, self.player),
                    state.locations_checked,
                )
        self.assertTrue(self.multiworld.can_beat_game(state))


class _FakeReachState:
    """Minimal stand-in for AP's CollectionState -- only ``can_reach_region``
    is needed, unlike test_requirements.py's FakeState (has/count), since
    can_warp_to_start is a Rule over region reachability, not items."""

    def __init__(self, reachable_regions: set[str]) -> None:
        self._reachable_regions = reachable_regions

    def can_reach_region(self, name: str, player: int) -> bool:
        assert player == 1
        return name in self._reachable_regions


class TestCanWarpToStart(unittest.TestCase):
    """Unit tests for logic/regions.py's can_warp_to_start against a fake
    reachability oracle -- independent of any particular generated world's
    origin_region_name. Under starting_room "vanilla"/"save_stations" that
    origin is always itself one of the 18 save-station candidates and thus
    always trivially reachable (see can_warp_to_start's own docstring for
    why that makes the *wired-in* graph edges a no-op there); testing the
    bare Rule here against a stand-in oracle exercises the "any of the 18"
    logic on its own, decoupled from that wrinkle, and matches what a
    genuinely non-save-station "anywhere" start needs it to do."""

    def setUp(self) -> None:
        self.db = load_game_database()
        self.rule = can_warp_to_start(self.db, player=1)

    def test_false_when_nothing_collected_and_no_save_station_reachable(self) -> None:
        self.assertFalse(self.rule(_FakeReachState(set())))

    def test_true_once_any_save_station_is_reachable(self) -> None:
        candidate = self.db.starting_location_candidates("save_stations")[3]
        self.assertTrue(self.rule(_FakeReachState({candidate.ap_name})))

    def test_false_when_only_a_non_save_station_anywhere_candidate_is_reachable(self) -> None:
        # A room that's a valid "anywhere" start but not one of the 18 save
        # stations (e.g. a boss arena) must not count -- can_warp_to_start
        # stays keyed on the fixed 18-room set regardless of pool.
        save_stations = set(self.db.starting_location_candidates("save_stations"))
        anywhere_only = next(
            c for c in self.db.starting_location_candidates("anywhere") if c not in save_stations
        )
        self.assertFalse(self.rule(_FakeReachState({anywhere_only.ap_name})))


class TestWarpToStartWiring(MP2TestBase):
    """create_regions' actual graph wiring (as opposed to the bare Rule
    above): with warp_to_start at its default (on), every one of the 18
    save-station regions other than the origin gets an unconditional exit
    straight to origin_region_name."""

    def _warp_edge_exists(self, source_name: str) -> bool:
        region = self.multiworld.get_region(source_name, self.player)
        return any(
            exit_.connected_region is not None
            and exit_.connected_region.name == self.world.origin_region_name
            for exit_ in region.exits
        )

    def test_every_non_origin_save_station_has_a_warp_edge(self) -> None:
        db = load_game_database()
        for node_id in db.starting_location_candidates("save_stations"):
            if node_id.ap_name == self.world.origin_region_name:
                continue
            with self.subTest(save_station=node_id.ap_name):
                self.assertTrue(self._warp_edge_exists(node_id.ap_name))


class TestWarpToStartDisabledAddsNoEdges(MP2TestBase):
    options = {"warp_to_start": False}

    def test_no_save_station_gets_a_warp_edge(self) -> None:
        db = load_game_database()
        for node_id in db.starting_location_candidates("save_stations"):
            if node_id.ap_name == self.world.origin_region_name:
                continue
            region = self.multiworld.get_region(node_id.ap_name, self.player)
            for exit_ in region.exits:
                with self.subTest(save_station=node_id.ap_name, exit=exit_.name):
                    self.assertNotIn("Warp to Start", exit_.name)


class TestStartingRoomSaveStationsStillGenerates(MP2TestBase):
    """starting_room="save_stations" must still produce a valid,
    self-consistent region graph -- origin_region_name always one of the
    18 candidates, reachable, and matching world.starting_location."""

    options = {"starting_room": "save_stations"}

    def test_origin_region_name_is_a_save_station_candidate(self) -> None:
        db = load_game_database()
        candidates = {c.ap_name for c in db.starting_location_candidates("save_stations")}
        self.assertIn(self.world.origin_region_name, candidates)
        self.assertEqual(self.world.starting_location.ap_name, self.world.origin_region_name)

    def test_origin_region_is_reachable(self) -> None:
        state = CollectionState(self.multiworld)
        self.assertTrue(state.can_reach_region(self.world.origin_region_name, self.player))


class TestStartingRoomAnywhereStillGenerates(MP2TestBase):
    """starting_room="anywhere" must also still produce a valid,
    self-consistent region graph, even though the chosen room may have no
    save station of its own (unlike the "save_stations" pool above)."""

    options = {"starting_room": "anywhere"}

    def test_origin_region_name_is_an_anywhere_candidate(self) -> None:
        db = load_game_database()
        candidates = {c.ap_name for c in db.starting_location_candidates("anywhere")}
        self.assertIn(self.world.origin_region_name, candidates)
        self.assertEqual(self.world.starting_location.ap_name, self.world.origin_region_name)

    def test_origin_region_is_reachable(self) -> None:
        state = CollectionState(self.multiworld)
        self.assertTrue(state.can_reach_region(self.world.origin_region_name, self.player))


class TestStartingRoomLightWorldOnlyStillGenerates(MP2TestBase):
    options = {"starting_room": "anywhere", "starting_room_light_world_only": True}

    def test_origin_region_is_in_a_light_region(self) -> None:
        db = load_game_database()
        _light_regions, dark_regions = db.light_dark_regions()
        self.assertNotIn(self.world.starting_location.region, dark_regions)
