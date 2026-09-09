"""Guards against ``version.txt`` and ``archipelago.json``'s ``world_version``
drifting apart -- see PLAN.md's task notes on deduping the apworld version.

Two independent copies of the same version string used to exist:
``version.txt`` (read at runtime via ``utils.get_apworld_version`` for
``slot_data``/client display) and ``archipelago.json``'s ``world_version``
(read by the MultiWorldGG framework itself, e.g.
``test/general/test_world_manifest.py``, which also requires it to be a
bare ``major.minor.build`` digit string with no prefix -- so that's the
format ``version.txt`` is normalized to as well, dropping the ``v`` prefix
it used to carry).
"""

from __future__ import annotations

import json
import unittest

from .. import utils


class TestVersionsAgree(unittest.TestCase):
    def test_version_txt_matches_archipelago_json(self) -> None:
        version_txt = utils.get_apworld_version()

        # archipelago.json lives at the package root, not under data/, so
        # it isn't reachable through data.load_json (which is scoped to
        # the data/ subpackage) -- read it the same pkgutil-based way
        # get_apworld_version reads version.txt, for the same
        # zip-safety reasons (PLAN.md: "works when the world is loaded
        # straight out of a built .apworld zip").
        import pkgutil

        raw = pkgutil.get_data("worlds.metroidprime2", "archipelago.json")
        assert raw is not None, "archipelago.json missing from metroidprime2 package"
        manifest = json.loads(raw.decode())

        self.assertEqual(
            version_txt,
            manifest["world_version"],
            "metroidprime2/version.txt and archipelago.json's world_version have drifted apart",
        )

        # Belt and braces: keep version.txt in the same digit-only
        # 'major.minor.build' shape test_world_manifest.py already
        # enforces for archipelago.json's world_version, so a future
        # edit to version.txt alone (without touching archipelago.json)
        # still gets caught here even if it accidentally still matches.
        parts = version_txt.split(".")
        self.assertEqual(len(parts), 3, "version.txt must be 'major.minor.build'")
        for part in parts:
            self.assertTrue(part.isdigit(), "version.txt may only contain numbers and '.'")


if __name__ == "__main__":
    unittest.main()
