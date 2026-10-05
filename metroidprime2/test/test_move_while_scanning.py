"""Tests for move-while-scanning: a single CTWK-Player tweak field flip
(``client/patcher_runner.py``'s ``install_move_while_scanning``) and the
option's route from the YAML into the ``.apmp2``'s options.json.

Unlike warp-to-start/spring-ball, this feature needs no DOL asm and no
``_apply_patches`` hook at all -- it just mutates a tweak resource directly
on the ``PatcherEditor``, so there is no in-game half to verify beyond that
single field write (confirmed against a real ISO via
``open-prime-rando``'s own export tests, PLAN.md section T).
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile

from .bases import MP2TestBase

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None


class _MoveWhileScanningOptionTest(MP2TestBase):
    """Like warp-to-start/spring-ball, move-while-scanning has no field in
    OPR's ``RandoConfiguration`` (config.json is validated with
    ``extra="forbid"``), so it travels in options.json instead -- which is
    exactly where ``patcher_runner.patch_iso_with_ap`` reads it back from."""

    expected: bool

    def test_flag_lands_in_options_json(self) -> None:
        if type(self) is _MoveWhileScanningOptionTest:
            self.skipTest("base class")
        with tempfile.TemporaryDirectory() as output_directory:
            self.world.generate_output(output_directory)
            (container_path,) = pathlib.Path(output_directory).glob("*.apmp2")
            with zipfile.ZipFile(container_path) as container:
                options = json.loads(container.read("options.json"))
                config = json.loads(container.read("config.json"))
        self.assertNotIn("move_while_scanning", config)
        self.assertEqual(options["move_while_scanning"], self.expected)


class TestMoveWhileScanningEnabled(_MoveWhileScanningOptionTest):
    options = {"move_while_scanning": True}
    expected = True


class TestMoveWhileScanningDisabledByDefault(_MoveWhileScanningOptionTest):
    expected = False


class _FakeScanVisor:
    def __init__(self) -> None:
        self.scan_freezes_game = True


class _FakeTweakPlayer:
    def __init__(self) -> None:
        self.scan_visor = _FakeScanVisor()


class _FakeEditor:
    """Enough of ``PatcherEditor`` for ``install_move_while_scanning``: an
    ``edit_tweak`` context manager yielding a mutable tweak, matching the
    real ``edit_tweak``'s ``yield prop`` / implicit ``set_properties``
    shape (the fake just leaves the mutation on the same object, since
    there's no separate serialize step to verify here)."""

    def __init__(self) -> None:
        self.tweak = _FakeTweakPlayer()

    @contextlib.contextmanager
    def edit_tweak(self, tweak_class: object):
        yield self.tweak


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestInstallMoveWhileScanning(unittest.TestCase):
    """``install_move_while_scanning`` must flip exactly
    ``TweakPlayer.scan_visor.scan_freezes_game`` and nothing else, via the
    same ``editor.edit_tweak`` context manager
    ``damage_changes.apply_damage_changes`` uses upstream."""

    def test_disables_scan_freezes_game(self) -> None:
        from ..client.patcher_runner import install_move_while_scanning

        editor = _FakeEditor()
        install_move_while_scanning(editor)
        self.assertFalse(editor.tweak.scan_visor.scan_freezes_game)
