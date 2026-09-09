"""M1 tests: logic/regions.py -- the generated region/entrance graph. See
``PLAN.md`` sections E and K (M1).
"""

from __future__ import annotations

import re

from BaseClasses import CollectionState

from ..items import ITEM_TABLE
from ..locations import LOCATION_TABLE
from ..logic.db_reader import Node, load_game_database
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

    def test_sky_temple_key_9_unreachable_at_start(self) -> None:
        location = LOCATION_TABLE[15]
        self.assertEqual("Sky Temple Grounds: Accursed Lake - Pickup (Sky Temple Key 9)", location.name)
        self.assertFalse(self.can_reach_location(location.name))

    def test_dark_torvus_key_3_unreachable_at_start(self) -> None:
        location = LOCATION_TABLE[69]
        self.assertEqual("Dark Torvus Bog: Venomous Pond - Pickup (Dark Torvus Key 3)", location.name)
        self.assertFalse(self.can_reach_location(location.name))

    def test_ing_hive_key_1_unreachable_at_start(self) -> None:
        location = LOCATION_TABLE[100]
        self.assertEqual("Ing Hive: Culling Chamber - Pickup (Ing Hive Key 1)", location.name)
        self.assertFalse(self.can_reach_location(location.name))


class TestLudicrousTricksStillGenerates(MP2TestBase):
    """Setting every trick to its hardest (ludicrous) difficulty must still
    produce a valid, fully-beatable region graph. No custom test methods
    are needed here: setting `options` makes WorldTestBase automatically
    run test_all_state_can_reach_everything / test_empty_state_can_reach_
    something / test_fill for this subclass."""

    options = {"trick_level": "ludicrous"}


class TestVanillaPlacement(MP2TestBase):
    """Lock the vanilla item onto every one of the 119 pickup locations
    (derived from each pickup node's own name) and check the game is still
    beatable -- i.e. the vendored vanilla game itself satisfies our own
    compiled logic."""

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
