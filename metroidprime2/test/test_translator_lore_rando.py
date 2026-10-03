"""Tests for translator lore hologram color randomization
(``translator_lore_rando``): the per-seed assignment
(``logic/translator_gate_rando.py``'s ``build_translator_lore_assignment``),
the client-side SCLY patch's data table and registration
(``client/lore_translator_patch.py``), and the option's route through logic
and into the ``.apmp2``'s options.json.

The in-game half (does the recolored hologram look right and only open
for its new translator) can only be checked against a real ISO -- see
``client/lore_translator_patch.py``'s docstring and manual test MT16's
``lore_colors`` variant.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import random
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast

from ..client import lore_translator_patch
from ..hint_scans import TRANSLATOR_LORE_HINT_SCANS
from ..logic import regions
from ..logic.db_reader import load_game_database
from ..logic.translator_gate_rando import TRANSLATOR_COLORS, build_translator_lore_assignment
from ..options import TranslatorLoreRando
from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_RDS_AVAILABLE = importlib.util.find_spec("retro_data_structures") is not None


class _FakeWorld:
    def __init__(self, translator_lore_rando: int, seed: int = 0) -> None:
        self.options = SimpleNamespace(translator_lore_rando=SimpleNamespace(value=translator_lore_rando))
        self.random = random.Random(seed)


def _lore_nodes() -> dict[int, Any]:
    """``{string_asset_id: Node}`` for the 22 lore hologram hint nodes."""
    return {
        node.string_asset_id: node
        for node in load_game_database().all_nodes()
        if node.node_type == "hint" and node.string_asset_id in lore_translator_patch.LORE_HOLOGRAMS
    }


class TestBuildTranslatorLoreAssignment(unittest.TestCase):
    def test_vanilla_returns_empty_without_drawing(self) -> None:
        world = _FakeWorld(TranslatorLoreRando.option_vanilla)
        state = world.random.getstate()
        self.assertEqual({}, build_translator_lore_assignment(cast(Any, world)))
        self.assertEqual(state, world.random.getstate())

    def test_full_random_assigns_every_hologram_a_color(self) -> None:
        world = _FakeWorld(TranslatorLoreRando.option_full_random, seed=1)
        assignment = build_translator_lore_assignment(cast(Any, world))
        self.assertEqual({hint_scan.strg_id for hint_scan in TRANSLATOR_LORE_HINT_SCANS}, set(assignment))
        for color in assignment.values():
            self.assertIn(color, TRANSLATOR_COLORS)

    def test_full_random_actually_moves_colors(self) -> None:
        vanilla = {hint_scan.strg_id: hint_scan.translator for hint_scan in TRANSLATOR_LORE_HINT_SCANS}
        world = _FakeWorld(TranslatorLoreRando.option_full_random, seed=1)
        assignment = build_translator_lore_assignment(cast(Any, world))
        self.assertNotEqual(vanilla, assignment)
        self.assertGreater(len(set(assignment.values())), 1)


class TestLoreHologramTable(unittest.TestCase):
    def test_keys_match_translator_lore_hint_scans(self) -> None:
        self.assertEqual(
            {hint_scan.strg_id for hint_scan in TRANSLATOR_LORE_HINT_SCANS},
            set(lore_translator_patch.LORE_HOLOGRAMS),
        )

    def test_vanilla_colors_match_hint_scans_and_the_vendored_db(self) -> None:
        nodes = _lore_nodes()
        for hint_scan in TRANSLATOR_LORE_HINT_SCANS:
            with self.subTest(hint_scan.room):
                hologram = lore_translator_patch.LORE_HOLOGRAMS[hint_scan.strg_id]
                self.assertEqual(hint_scan.translator.lower(), hologram.vanilla_color)
                translators = [
                    item["data"]["name"] for item in nodes[hint_scan.strg_id].requirement_to_collect["data"]["items"]
                ]
                self.assertEqual(["Scan", hint_scan.translator], translators)

    def test_mlvl_and_mrea_match_the_vendored_db(self) -> None:
        db = load_game_database()
        nodes = _lore_nodes()
        for strg_id, hologram in lore_translator_patch.LORE_HOLOGRAMS.items():
            node = nodes[strg_id]
            with self.subTest(node.ap_name):
                self.assertEqual(db.mlvl_for_region(node.id.region), hologram.mlvl_id)
                self.assertEqual(db.regions[node.id.region].areas[node.id.area].asset_id, hologram.mrea_id)

    def test_every_color_has_a_texture_and_glow(self) -> None:
        colors = {color.lower() for color in TRANSLATOR_COLORS}
        self.assertEqual(colors, set(lore_translator_patch._HOLOGRAM_TEXTURES))
        self.assertEqual(colors, set(lore_translator_patch._GLOW_MODELS))

    @unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
    def test_glow_models_match_open_prime_randos_gate_glows(self) -> None:
        from open_prime_rando.echoes.translator_gates import TRANSLATOR_DATA

        for color, glow_model in lore_translator_patch._GLOW_MODELS.items():
            self.assertEqual(TRANSLATOR_DATA[color].glow_model, glow_model)


class _FakeInstance:
    def __init__(self, props: Any) -> None:
        self.props = props

    def get_properties_as(self, type_cls: object) -> Any:
        return self.props

    @contextmanager
    def edit_properties(self, type_cls: object):
        yield self.props


class _FakeArea:
    def __init__(self, instances: dict[int, _FakeInstance]) -> None:
        self._instances = instances

    def get_instance(self, instance_id: int) -> _FakeInstance:
        return self._instances[instance_id]


class _FakeEditor:
    def __init__(self) -> None:
        self.duplicated: list[tuple[int, str]] = []
        self.new_model = SimpleNamespace(raw=SimpleNamespace(material_sets=[SimpleNamespace(texture_file_ids=[0])]))

    def duplicate_asset(self, asset_id: int, new_name: str) -> int:
        self.duplicated.append((asset_id, new_name))
        return 0xC0FFEE

    def get_file(self, asset_id: int, type_cls: object) -> Any:
        assert asset_id == 0xC0FFEE
        return self.new_model


@unittest.skipUnless(_RDS_AVAILABLE, "retro_data_structures is not installed")
class TestRecolorLoreHologram(unittest.TestCase):
    def _fixture(self) -> tuple[_FakeEditor, _FakeArea, lore_translator_patch.LoreHologram, dict[str, Any]]:
        from retro_data_structures.enums.echoes import PlayerItemEnum

        hologram = lore_translator_patch.LORE_HOLOGRAMS[0x24E69725]  # Mining Plaza, vanilla Amber
        relay = SimpleNamespace(conditional1=SimpleNamespace(player_item=PlayerItemEnum.AmberTranslator))
        glow = SimpleNamespace(model=0xB9824E7E)
        holo = SimpleNamespace(model=0x5553ECE1)
        area = _FakeArea(
            {
                hologram.relay_id: _FakeInstance(relay),
                hologram.glow_id: _FakeInstance(glow),
                hologram.hologram_id: _FakeInstance(holo),
            }
        )
        return _FakeEditor(), area, hologram, {"relay": relay, "glow": glow, "holo": holo}

    def test_recolors_requirement_glow_and_hologram(self) -> None:
        from retro_data_structures.enums.echoes import PlayerItemEnum

        editor, area, hologram, props = self._fixture()
        lore_translator_patch.recolor_lore_hologram(
            editor, None, cast(Any, area), hologram=hologram, color="cobalt"
        )

        self.assertEqual(PlayerItemEnum.CobaltTranslator, props["relay"].conditional1.player_item)
        self.assertEqual(0xF2DE555A, props["glow"].model)
        self.assertEqual([(0x5553ECE1, "translator_lore_holo_2027d.CMDL")], editor.duplicated)
        self.assertEqual(0xC0FFEE, props["holo"].model)
        self.assertEqual([0x2C56D2D4], editor.new_model.raw.material_sets[0].texture_file_ids)

    def test_rejects_unknown_color(self) -> None:
        editor, area, hologram, _props = self._fixture()
        with self.assertRaises(ValueError):
            lore_translator_patch.recolor_lore_hologram(
                editor, None, cast(Any, area), hologram=hologram, color="unlocked"
            )


class _FakeAreaPatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, Any]] = []

    def add_raw_function(self, mlvl_id: int, mrea_id: int, func: Any) -> None:
        self.calls.append((mlvl_id, mrea_id, func))


class TestRegister(unittest.TestCase):
    def test_registers_only_changed_holograms(self) -> None:
        patcher = _FakeAreaPatcher()
        lore_translator_patch.register(
            cast(Any, patcher),
            {0x24E69725: "amber", 0x987884FB: "emerald"},  # Mining Plaza unchanged, Meeting Grounds moved
        )

        self.assertEqual(1, len(patcher.calls))
        mlvl_id, mrea_id, func = patcher.calls[0]
        hologram = lore_translator_patch.LORE_HOLOGRAMS[0x987884FB]
        self.assertEqual((hologram.mlvl_id, hologram.mrea_id), (mlvl_id, mrea_id))
        self.assertEqual(lore_translator_patch.recolor_lore_hologram, func.func)
        self.assertEqual({"hologram": hologram, "color": "emerald"}, func.keywords)


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestTranslatorLoreColorsInstalled(unittest.TestCase):
    def test_wraps_and_restores_register_world_changes(self) -> None:
        from open_prime_rando.echoes import patcher as opr_patcher

        from ..client.patcher_runner import translator_lore_colors_installed

        original = opr_patcher.register_world_changes
        with self.assertRaises(RuntimeError):
            with translator_lore_colors_installed({0x987884FB: "emerald"}):
                self.assertIsNot(opr_patcher.register_world_changes, original)
                raise RuntimeError("boom")
        self.assertIs(opr_patcher.register_world_changes, original)


def _options_json(test: MP2TestBase) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as output_directory:
        test.world.generate_output(output_directory)
        containers = list(pathlib.Path(output_directory).glob("*.apmp2"))
        test.assertEqual(1, len(containers))
        with zipfile.ZipFile(containers[0]) as container:
            return json.loads(container.read("options.json"))


class TestTranslatorLoreRandoDefault(MP2TestBase):
    def test_no_colors_in_options_json(self) -> None:
        self.assertEqual({}, self.world.translator_lore_assignment)
        self.assertEqual({}, _options_json(self)["translator_lore_colors"])

    def test_hint_nodes_keep_their_vanilla_requirement(self) -> None:
        for node in _lore_nodes().values():
            self.assertIs(node.requirement_to_collect, regions._leave_requirement(self.world, node))


class TestTranslatorLoreRandoFullRandom(MP2TestBase):
    options = {"translator_lore_rando": "full_random"}

    def test_all_pickups_reachable(self) -> None:
        self.assert_all_locations_reachable()

    def test_options_json_carries_the_assignment(self) -> None:
        colors = _options_json(self)["translator_lore_colors"]
        self.assertEqual(
            {str(strg_id): color.lower() for strg_id, color in self.world.translator_lore_assignment.items()},
            colors,
        )
        self.assertEqual(len(TRANSLATOR_LORE_HINT_SCANS), len(colors))

    def test_hint_nodes_require_their_assigned_color(self) -> None:
        for strg_id, node in _lore_nodes().items():
            with self.subTest(node.ap_name):
                requirement = regions._leave_requirement(self.world, node)
                assert requirement is not None
                names = [item["data"]["name"] for item in requirement["data"]["items"]]
                self.assertEqual(["Scan", self.world.translator_lore_assignment[strg_id]], names)


if __name__ == "__main__":
    unittest.main()
