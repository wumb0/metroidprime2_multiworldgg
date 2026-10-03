"""Tests for Universal Tracker regeneration (``tracker_data.py`` and the
passthrough branch of ``MetroidPrime2World.generate_early``): a regen with a
different seed must reproduce the original generation's randomized state --
starting room, dock rando, translator gates and lore colors -- from slot
data alone.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from BaseClasses import MultiWorld
from Options import PerGameCommonOptions
from test.general import gen_steps, setup_multiworld
from worlds.AutoWorld import call_all

from .. import MetroidPrime2World, _slot_data_option_names, constants
from ..client.client import _send_mlvl_datastorage
from ..locations import location_name_to_id
from ..logic.db_reader import NodeId
from ..options import MetroidPrime2Options
from ..tracker_data import TRACKER_WORLD, decode_randomization, encode_randomization, map_page_index
from .bases import MP2TestBase

_RANDOMIZED_OPTIONS: dict[str, Any] = {
    "starting_room": "anywhere",
    "door_lock_rando": True,
    "elevator_rando": True,
    "portal_rando": True,
    "translator_gate_rando": "full_random_unlocked",
    "translator_lore_rando": "full_random",
}


def _entrance_map(multiworld: MultiWorld) -> dict[str, str | None]:
    return {
        entrance.name: entrance.connected_region.name if entrance.connected_region else None
        for region in multiworld.get_regions()
        for entrance in region.exits
    }


def _regen(slot_data: dict[str, Any], seed: int) -> MultiWorld:
    """Mimics Universal Tracker's regeneration: a fresh multiworld (different
    seed, default options) with ``re_gen_passthrough`` set and
    ``generation_is_fake`` flagged before any gen step runs."""
    from worlds import AutoWorld

    world_type = AutoWorld.AutoWorldRegister.world_types[MP2TestBase.game]
    multiworld = setup_multiworld(world_type, steps=(), seed=seed)
    multiworld.generation_is_fake = True  # type: ignore[attr-defined]
    multiworld.re_gen_passthrough = {MP2TestBase.game: slot_data}  # type: ignore[attr-defined]
    for step in gen_steps:
        call_all(multiworld, step)
    return multiworld


class TestTrackerRegen(MP2TestBase):
    options = _RANDOMIZED_OPTIONS

    def _slot_data(self) -> dict[str, Any]:
        slot_data = self.world.options.as_dict(*_slot_data_option_names())
        slot_data.update(encode_randomization(self.world))
        # Slot data reaches UT through the server as JSON.
        return json.loads(json.dumps(slot_data))

    def test_slot_data_round_trips(self) -> None:
        restored = decode_randomization(self._slot_data())
        assert restored is not None
        self.assertEqual(self.world.starting_location, restored.starting_location)
        self.assertEqual(self.world.translator_gate_assignment, restored.translator_gates)
        self.assertEqual(self.world.translator_lore_assignment, restored.translator_lore)
        self.assertEqual(self.world.dock_rando, restored.dock_rando)

    def test_randomization_is_actually_randomized(self) -> None:
        # Guards the round-trip test above against passing vacuously.
        self.assertTrue(self.world.dock_rando.door_lock)
        self.assertTrue(self.world.dock_rando.elevator)
        self.assertTrue(self.world.dock_rando.portal)
        self.assertTrue(self.world.translator_gate_assignment)
        self.assertTrue(self.world.translator_lore_assignment)

    def test_regen_reproduces_randomized_state(self) -> None:
        slot_data = self._slot_data()
        regen = _regen(slot_data, seed=self.multiworld.seed + 1 if self.multiworld.seed else 12345)
        regen_world = regen.worlds[1]

        self.assertEqual(self.world.origin_region_name, regen_world.origin_region_name)
        self.assertEqual(self.world.starting_location, regen_world.starting_location)
        self.assertEqual(self.world.translator_gate_assignment, regen_world.translator_gate_assignment)
        self.assertEqual(self.world.translator_lore_assignment, regen_world.translator_lore_assignment)
        self.assertEqual(self.world.dock_rando, regen_world.dock_rando)
        self.assertEqual(_entrance_map(self.multiworld), _entrance_map(regen))

    def test_old_slot_data_falls_back(self) -> None:
        slot_data = self._slot_data()
        for key in ("starting_location", "translator_gates", "translator_lore", "dock_rando"):
            slot_data.pop(key)
        self.assertIsNone(decode_randomization(slot_data))


class TestTrackerRegenVanilla(MP2TestBase):
    options: dict[str, Any] = {}

    def test_regen_vanilla(self) -> None:
        slot_data = self.world.options.as_dict(*_slot_data_option_names())
        slot_data.update(encode_randomization(self.world))
        regen = _regen(json.loads(json.dumps(slot_data)), seed=777)
        self.assertEqual(self.world.origin_region_name, regen.worlds[1].origin_region_name)
        self.assertEqual(_entrance_map(self.multiworld), _entrance_map(regen))


class TestNodeIdRoundTrip(unittest.TestCase):
    def test_node_with_slash_free_parts(self) -> None:
        node = NodeId(region="Temple Grounds", area="Landing Site", node="Save Station")
        from ..tracker_data import _decode_node, _encode_node

        self.assertEqual(node, _decode_node(json.loads(json.dumps(_encode_node(node)))))


class TestYamlLessGeneration(unittest.TestCase):
    def test_flag_enabled(self) -> None:
        self.assertTrue(MetroidPrime2World.ut_can_gen_without_yaml)

    def test_slot_data_covers_every_world_option(self) -> None:
        # A yaml-less regen starts from default options and overlays slot
        # data, so any option missing from it would silently revert to its
        # default in the tracker. Only core item-placement/server options
        # (none of which affect logic) may be left out.
        world_options = {
            name
            for name in MetroidPrime2Options.type_hints
            if name not in PerGameCommonOptions.type_hints
        }
        self.assertEqual(world_options, set(_slot_data_option_names()))


class TestMapPack(unittest.TestCase):
    TRACKER_DIR = Path(__file__).resolve().parents[1] / "tracker"

    def _json(self, *parts: str) -> Any:
        return json.loads(self.TRACKER_DIR.joinpath(*parts).read_text(encoding="utf-8"))

    def _flat_locations(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        found: list[tuple[dict[str, Any], dict[str, Any]]] = []

        def walk(node: dict[str, Any]) -> None:
            if "map_locations" in node:
                found.extend((node, map_location) for map_location in node["map_locations"])
            for child in node.get("children", []):
                walk(child)

        for node in self._json("locations", "locations.json"):
            walk(node)
        return found

    def test_groups_cover_exactly_the_maps(self) -> None:
        map_names = [m["name"] for m in self._json("maps", "maps.json")]
        grouped = [name for _, names in TRACKER_WORLD["map_page_groups"] for name in names]
        self.assertEqual(sorted(map_names), sorted(grouped))
        for m in self._json("maps", "maps.json"):
            self.assertTrue((self.TRACKER_DIR / m["img"]).is_file(), m["img"])

    def test_every_location_placed_exactly_once(self) -> None:
        names = [section["name"] for node, _ in self._flat_locations() for section in node["sections"]]
        self.assertEqual(sorted(location_name_to_id), sorted(names))

    def test_dots_unique_and_inside_image(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        sizes = {m["name"]: Image.open(self.TRACKER_DIR / m["img"]).size for m in self._json("maps", "maps.json")}
        seen: set[tuple[str, int, int]] = set()
        for _, map_location in self._flat_locations():
            key = (map_location["map"], map_location["x"], map_location["y"])
            self.assertNotIn(key, seen, "two locations share a pixel; UT would merge their dots")
            seen.add(key)
            width, height = sizes[map_location["map"]]
            self.assertTrue(0 <= map_location["x"] < width and 0 <= map_location["y"] < height, key)

    def test_locations_sit_on_their_own_region_map(self) -> None:
        for node, map_location in self._flat_locations():
            region = node["name"].split(":")[0]
            self.assertEqual(region, map_location["map"], node["name"])

    def test_area_maps_reference_real_maps(self) -> None:
        map_names = {m["name"] for m in self._json("maps", "maps.json")}
        for areas in self._json("area_maps.json").values():
            self.assertLessEqual(set(areas.values()), map_names)

    def test_map_page_index(self) -> None:
        map_names = [m["name"] for m in self._json("maps", "maps.json")]
        for mlvl, areas in self._json("area_maps.json").items():
            for area, map_name in areas.items():
                self.assertEqual(map_names.index(map_name), map_page_index(f"{mlvl}:{area}"))
        for garbage in ("", None, "nonsense", "1:2:3", "DEADBEEF:0", 12345):
            self.assertEqual(-1, map_page_index(garbage))

    def test_client_key_matches_tracker_setting(self) -> None:
        self.assertEqual(
            TRACKER_WORLD["map_page_setting_key"].format(team=1, player=7),
            constants.AREA_DATASTORAGE_KEY.format(team=1, slot=7),
        )

    def test_accepted_by_universal_tracker(self) -> None:
        try:
            from worlds.tracker import UTMapTabData
        except ImportError:
            self.skipTest("Universal Tracker not available")
        data = UTMapTabData(7, 1, **TRACKER_WORLD)
        self.assertEqual("metroidprime2_area_1_7", data.map_page_setting_key)
        self.assertEqual(-1, data.map_page_index("nonsense"))


class TestAreaDatastorage(unittest.TestCase):
    def _ctx(self, mlvl: int | None, area: int | None) -> Any:
        sent: list[list[dict[str, Any]]] = []

        async def send_msgs(messages: list[dict[str, Any]]) -> None:
            sent.append(messages)

        interface = SimpleNamespace(current_mlvl=lambda: mlvl, current_area_id=lambda: area)
        return SimpleNamespace(
            game_interface=interface,
            slot=3,
            team=0,
            last_sent_mlvl=None,
            last_sent_area=None,
            send_msgs=send_msgs,
            sent=sent,
        )

    def test_sends_mlvl_and_area_then_only_changes(self) -> None:
        ctx = self._ctx(0x3BFA3EFF, 5)
        asyncio.run(_send_mlvl_datastorage(ctx))
        self.assertEqual(
            [("metroidprime2_mlvl_0_3", 0x3BFA3EFF), ("metroidprime2_area_0_3", "3BFA3EFF:5")],
            [(m["key"], m["operations"][0]["value"]) for m in ctx.sent[0]],
        )
        asyncio.run(_send_mlvl_datastorage(ctx))
        self.assertEqual(1, len(ctx.sent), "unchanged location must not resend")

        ctx.game_interface.current_area_id = lambda: 6
        asyncio.run(_send_mlvl_datastorage(ctx))
        self.assertEqual(["metroidprime2_area_0_3"], [m["key"] for m in ctx.sent[1]])

    def test_nothing_sent_outside_a_world(self) -> None:
        ctx = self._ctx(None, None)
        asyncio.run(_send_mlvl_datastorage(ctx))
        self.assertEqual([], ctx.sent)
