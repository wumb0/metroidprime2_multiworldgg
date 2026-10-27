"""Tests for ``flying_ing_caches_without_dark_visor``: the SCLY rewrite
(``client/flying_ing_cache_patch.py``), its install hook, the option's route
into options.json, and the logic edges it relaxes
(``logic/regions.py``'s ``FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS``).

Whether a shot really lands on the invisible cache can only be checked in
game -- see the patch module's docstring for the reverse engineering.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile
from dataclasses import dataclass
from typing import Any, cast

from ..client import flying_ing_cache_patch
from ..logic.db_reader import load_game_database
from ..logic.regions import (
    _DARK_VISOR,
    FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS,
    _replace_cache_dark_visor,
)
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None

_BATTLEGROUND = next(n for n in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS if n.area == "Battleground")


def _location_name(node_id: Any) -> str:
    return f"{node_id.region}: {node_id.area} - {node_id.node}"


def _mentions_dark_visor(req: dict) -> bool:
    return '"DarkVisor"' in json.dumps(req)


class TestCacheEdgesInLogicDatabase(unittest.TestCase):
    """The replacement table against the vendored logic DB, so a resync that
    moves a key or reshapes an edge fails here rather than at generation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = load_game_database()
        cls.incoming = {
            target: [
                (node, node.connections[target.node])
                for node in cls.db.all_nodes()
                if node.id.region == target.region and node.id.area == target.area and target.node in node.connections
            ]
            for target in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS
        }

    def test_table_is_exactly_the_sky_temple_key_pickups(self) -> None:
        key_pickups = {
            node.id
            for node in self.db.all_nodes()
            if node.node_type == "pickup" and (node.location_data or {}).get("original_model") == "SkyTempleKey"
        }
        self.assertEqual(set(FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS), key_pickups)

    def test_patched_rooms_match_the_table(self) -> None:
        asset_ids = {self.db.regions[n.region].areas[n.area].asset_id for n in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS}
        self.assertEqual(asset_ids, {mrea for _, mrea in flying_ing_cache_patch.FLYING_ING_CACHE_ROOMS})

    def test_every_incoming_edge_loses_its_dark_visor(self) -> None:
        for target, replacement in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS.items():
            self.assertTrue(self.incoming[target], target)
            for source, req in self.incoming[target]:
                with self.subTest(edge=f"{source.ap_name} -> {target.node}"):
                    self.assertTrue(_mentions_dark_visor(req))
                    relaxed = _replace_cache_dark_visor(req, replacement)
                    self.assertNotIn(_DARK_VISOR, relaxed["data"]["items"])
                    self.assertEqual(_mentions_dark_visor(relaxed), replacement is not None)

    def test_only_battleground_keeps_a_dark_visor_alternative(self) -> None:
        kept = {n for n, r in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS.items() if r is not None}
        self.assertEqual(kept, {_BATTLEGROUND})


class TestReplaceCacheDarkVisor(unittest.TestCase):
    _SPACE_JUMP = {"type": "resource", "data": {"type": "items", "name": "SpaceJump", "amount": 1, "negate": False}}
    _TRICK = {"type": "resource", "data": {"type": "tricks", "name": "Dash", "amount": 2, "negate": False}}

    def _and(self, *items: dict) -> dict:
        return {"type": "and", "data": {"comment": None, "items": list(items)}}

    def test_bare_dark_visor_becomes_trivial(self) -> None:
        self.assertEqual(_replace_cache_dark_visor(_DARK_VISOR, None), self._and())

    def test_drops_dark_visor_and_keeps_siblings(self) -> None:
        req = self._and(_DARK_VISOR, self._SPACE_JUMP)
        self.assertEqual(_replace_cache_dark_visor(req, None), self._and(self._SPACE_JUMP))

    def test_substitutes_the_replacement_in_place(self) -> None:
        req = self._and(self._SPACE_JUMP, _DARK_VISOR)
        self.assertEqual(_replace_cache_dark_visor(req, self._TRICK), self._and(self._SPACE_JUMP, self._TRICK))

    def test_does_not_mutate_the_database_requirement(self) -> None:
        req = self._and(_DARK_VISOR, self._SPACE_JUMP)
        _replace_cache_dark_visor(req, None)
        self.assertEqual(req, self._and(_DARK_VISOR, self._SPACE_JUMP))

    def test_rejects_edges_without_exactly_one_top_level_dark_visor(self) -> None:
        nested = {"type": "or", "data": {"comment": None, "items": [_DARK_VISOR, self._SPACE_JUMP]}}
        for req in (self._and(self._SPACE_JUMP), self._and(_DARK_VISOR, _DARK_VISOR), self._and(nested), nested):
            with self.subTest(req=req), self.assertRaises(ValueError):
                _replace_cache_dark_visor(req, None)


class _CacheReachabilityTest(MP2TestBase):
    """Everything but the Dark Visor collected: which key caches can be
    reached."""

    reachable_without_dark_visor: frozenset

    def test_key_caches_without_dark_visor(self) -> None:
        if type(self) is _CacheReachabilityTest:
            self.skipTest("base class")
        self.collect_all_but(["Dark Visor"])
        for node_id in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS:
            with self.subTest(location=node_id.area):
                self.assertEqual(
                    self.can_reach_location(_location_name(node_id)),
                    node_id in self.reachable_without_dark_visor,
                )

    def test_every_key_cache_reachable_with_dark_visor(self) -> None:
        if type(self) is _CacheReachabilityTest:
            self.skipTest("base class")
        self.collect_all_but([])
        for node_id in FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS:
            with self.subTest(location=node_id.area):
                self.assertTrue(self.can_reach_location(_location_name(node_id)))


class TestCachesNeedDarkVisorByDefault(_CacheReachabilityTest):
    reachable_without_dark_visor = frozenset()


class TestCachesWithoutDarkVisor(_CacheReachabilityTest):
    options = {"flying_ing_caches_without_dark_visor": True}
    reachable_without_dark_visor = frozenset(FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS) - {_BATTLEGROUND}


class TestCachesWithoutDarkVisorAndInvisibleObjects(_CacheReachabilityTest):
    options = {"flying_ing_caches_without_dark_visor": True, "trick_invisibleobjects": "intermediate"}
    reachable_without_dark_visor = frozenset(FLYING_ING_CACHE_DARK_VISOR_REPLACEMENTS)


class _CacheOptionJsonTest(MP2TestBase):
    expected: bool

    def test_flag_lands_in_options_json(self) -> None:
        if type(self) is _CacheOptionJsonTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("flying_ing_caches_without_dark_visor", config)
        self.assertEqual(options["flying_ing_caches_without_dark_visor"], self.expected)


class TestCacheOptionEnabled(_CacheOptionJsonTest):
    options = {"flying_ing_caches_without_dark_visor": True}
    expected = True


class TestCacheOptionDisabledByDefault(_CacheOptionJsonTest):
    expected = False


@dataclass
class _FakeConnection:
    state: object
    message: object
    target: object


class _FakeProps:
    def __init__(self) -> None:
        self.active = False

    @property
    def editor_properties(self) -> _FakeProps:
        return self


class _FakeInstance:
    def __init__(self, instance_id: int, connections: list[_FakeConnection] | None = None) -> None:
        self.id = instance_id
        self.connections = list(connections or [])
        self.props = _FakeProps()
        self.edited_as: list[object] = []

    def remove_connection(self, connection: _FakeConnection) -> None:
        self.connections = [c for c in self.connections if c is not connection]

    def edit_properties(self, type_cls: object) -> Any:
        import contextlib

        self.edited_as.append(type_cls)
        return contextlib.nullcontext(self.props)


class _FakeArea:
    name = "Fake Defiled Shrine"

    def __init__(self, instances: dict[str, _FakeInstance]) -> None:
        self._instances = instances

    def get_instance(self, name: str) -> _FakeInstance:
        return self._instances[name]


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestMakeCacheShootable(unittest.TestCase):
    def _area(self, *, extra_hides: int = 0) -> tuple[_FakeArea, _FakeInstance, _FakeInstance]:
        from retro_data_structures.enums.echoes import Message, State

        dummy = _FakeInstance(0x52)
        war_chest = 0x89
        connections = [
            _FakeConnection(State.Entered, Message.Activate, war_chest),
            _FakeConnection(State.Exited, Message.Deactivate, war_chest),
            _FakeConnection(State.Entered, Message.Activate, dummy.id),
            _FakeConnection(State.Exited, Message.Deactivate, dummy.id),
        ]
        connections += [_FakeConnection(State.Exited, Message.Deactivate, dummy.id) for _ in range(extra_hides)]
        detector = _FakeInstance(0x8C, connections)
        area = _FakeArea({flying_ing_cache_patch.DETECTOR_NAME: detector, flying_ing_cache_patch.DUMMY_NAME: dummy})
        return area, detector, dummy

    def test_dummy_starts_active(self) -> None:
        from retro_data_structures.properties.echoes.objects import Actor

        area, _, dummy = self._area()
        flying_ing_cache_patch.make_cache_shootable(None, None, cast(Any, area))
        self.assertTrue(dummy.props.active)
        self.assertEqual(dummy.edited_as, [Actor])

    def test_only_the_dummy_hide_connection_is_removed(self) -> None:
        from retro_data_structures.enums.echoes import Message, State

        area, detector, dummy = self._area()
        flying_ing_cache_patch.make_cache_shootable(None, None, cast(Any, area))
        self.assertEqual(
            [(c.state, c.message, c.target) for c in detector.connections],
            [
                (State.Entered, Message.Activate, 0x89),
                (State.Exited, Message.Deactivate, 0x89),
                (State.Entered, Message.Activate, dummy.id),
            ],
        )

    def test_refuses_an_unexpected_room(self) -> None:
        area, _, _ = self._area(extra_hides=1)
        with self.assertRaises(AssertionError):
            flying_ing_cache_patch.make_cache_shootable(None, None, cast(Any, area))


class TestRegister(unittest.TestCase):
    def test_registers_every_key_room_once(self) -> None:
        registered: list[tuple[int, int, Any]] = []

        class _Patcher:
            def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
                registered.append((mlvl_id, mrea_id, func))

        flying_ing_cache_patch.register(cast(Any, _Patcher()))
        self.assertEqual({(m, r) for m, r, _ in registered}, set(flying_ing_cache_patch.FLYING_ING_CACHE_ROOMS))
        self.assertEqual(len(registered), 9)
        self.assertTrue(all(f is flying_ing_cache_patch.make_cache_shootable for _, _, f in registered))


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestInstalled(unittest.TestCase):
    def test_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import flying_ing_caches_shootable_installed

        original = opr_patcher.register_world_changes
        registered: list[tuple[int, int]] = []

        class _Patcher:
            def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
                registered.append((mlvl_id, mrea_id))

        opr_patcher.register_world_changes = lambda area_patcher, world_changes: None
        try:
            with flying_ing_caches_shootable_installed():
                opr_patcher.register_world_changes(cast(Any, _Patcher()), [])
        finally:
            opr_patcher.register_world_changes = original
        self.assertEqual(set(registered), set(flying_ing_cache_patch.FLYING_ING_CACHE_ROOMS))
