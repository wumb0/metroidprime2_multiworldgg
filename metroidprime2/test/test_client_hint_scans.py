"""Tests for ``client/client.py``'s ``_handle_hint_scans`` (PLAN.md section
Q.5): the Sky Temple Key pillar scan-completion poll. Mirrors
``test_goal_detection.py``'s approach -- a plain duck-typed fake context/
game-interface, no real ``MetroidPrime2Context``/Dolphin needed, since
``_handle_hint_scans`` only touches ``ctx.hint_scans``/``ctx.
sent_hint_scans``/``ctx.game_interface.read_scan_progress``/``ctx.
send_msgs``.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from typing import Any

# See test_deathlink.py's identical comment: importing client.client pulls
# in CommonClient, which without this env var (set before CommonClient's
# first import anywhere in the process) and the network_data_package stub
# below would shell out to pip / import every world package.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from NetUtils import HintStatus

from ..client.client import _handle_hint_scans


class _FakeGameInterface:
    def __init__(self, scan_progress: dict[int, int] | None) -> None:
        self.scan_progress = scan_progress
        self.read_calls = 0

    def read_scan_progress(self) -> dict[int, int] | None:
        self.read_calls += 1
        return self.scan_progress


class _FakeContext:
    def __init__(
        self,
        hint_scans: dict[int, tuple[int, int, int]],
        scan_progress: dict[int, int] | None,
        sent_hint_scans: set[int] | None = None,
    ) -> None:
        self.hint_scans = hint_scans
        self.sent_hint_scans: set[int] = set() if sent_hint_scans is None else sent_hint_scans
        self.game_interface = _FakeGameInterface(scan_progress)
        self.sent_msgs: list[list[dict[str, Any]]] = []

    async def send_msgs(self, msgs: list[dict[str, Any]]) -> None:
        self.sent_msgs.append(msgs)


def _run(ctx: _FakeContext) -> None:
    asyncio.run(_handle_hint_scans(ctx))  # type: ignore[arg-type]


class TestHandleHintScans(unittest.TestCase):
    def test_sends_one_createhints_batch_grouped_by_player(self) -> None:
        hint_scans = {
            0x111: (1, 100, HintStatus.HINT_PRIORITY),
            0x222: (1, 101, HintStatus.HINT_PRIORITY),
            0x333: (2, 200, HintStatus.HINT_PRIORITY),
        }
        ctx = _FakeContext(hint_scans, scan_progress={0x111: 255, 0x222: 255, 0x333: 255})

        _run(ctx)

        self.assertEqual(1, len(ctx.sent_msgs))
        messages = ctx.sent_msgs[0]
        by_player = {msg["player"]: sorted(msg["locations"]) for msg in messages}
        self.assertEqual({1: [100, 101], 2: [200]}, by_player)
        for msg in messages:
            self.assertEqual("CreateHints", msg["cmd"])
            self.assertEqual(HintStatus.HINT_PRIORITY, msg["status"])
        self.assertEqual({0x111, 0x222, 0x333}, ctx.sent_hint_scans)

    def test_mixed_statuses_produce_separate_createhints_messages(self) -> None:
        # Section R: a translator lore hint naming another player's item is
        # HINT_UNSPECIFIED, unlike every Sky Temple Key entry
        # (HINT_PRIORITY) -- even for the very same player, these must go
        # out as two separate CreateHints messages, never merged.
        hint_scans = {
            0x111: (1, 100, HintStatus.HINT_PRIORITY),
            0x222: (1, 101, HintStatus.HINT_UNSPECIFIED),
        }
        ctx = _FakeContext(hint_scans, scan_progress={0x111: 255, 0x222: 255})

        _run(ctx)

        self.assertEqual(1, len(ctx.sent_msgs))
        messages = ctx.sent_msgs[0]
        self.assertEqual(2, len(messages))
        by_status = {msg["status"]: sorted(msg["locations"]) for msg in messages}
        self.assertEqual({HintStatus.HINT_PRIORITY: [100], HintStatus.HINT_UNSPECIFIED: [101]}, by_status)
        for msg in messages:
            self.assertEqual("CreateHints", msg["cmd"])
            self.assertEqual(1, msg["player"])

    def test_partial_scan_progress_is_not_reported(self) -> None:
        hint_scans = {0x111: (1, 100, HintStatus.HINT_PRIORITY)}
        ctx = _FakeContext(hint_scans, scan_progress={0x111: 254})

        _run(ctx)

        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual(set(), ctx.sent_hint_scans)

    def test_not_resent_on_the_next_tick(self) -> None:
        hint_scans = {0x111: (1, 100, HintStatus.HINT_PRIORITY)}
        ctx = _FakeContext(hint_scans, scan_progress={0x111: 255})

        _run(ctx)
        self.assertEqual(1, len(ctx.sent_msgs))

        _run(ctx)
        # Still only the one CreateHints batch from the first tick -- the
        # second tick's read_scan_progress() shouldn't even be reached
        # (checked separately below), but even if it were, 0x111 is already
        # in sent_hint_scans.
        self.assertEqual(1, len(ctx.sent_msgs))

    def test_no_dolphin_read_once_everything_is_sent(self) -> None:
        hint_scans = {0x111: (1, 100, HintStatus.HINT_PRIORITY)}
        ctx = _FakeContext(hint_scans, scan_progress={0x111: 255})

        _run(ctx)
        self.assertEqual(1, ctx.game_interface.read_calls)

        _run(ctx)
        # set(ctx.hint_scans) <= ctx.sent_hint_scans now -- must short-circuit
        # before ever calling read_scan_progress() again.
        self.assertEqual(1, ctx.game_interface.read_calls)

    def test_none_scan_progress_read_is_treated_as_disconnected(self) -> None:
        hint_scans = {0x111: (1, 100, HintStatus.HINT_PRIORITY)}
        ctx = _FakeContext(hint_scans, scan_progress=None)

        _run(ctx)

        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual(set(), ctx.sent_hint_scans)

    def test_no_hint_scans_at_all_skips_the_dolphin_read(self) -> None:
        # sky_temple_key_hints != "scanned" and translator_lore_hints ==
        # "off" -> empty hint_scans (Q.4/Q.5, R.4).
        ctx = _FakeContext(hint_scans={}, scan_progress={0x111: 255})

        _run(ctx)

        self.assertEqual([], ctx.sent_msgs)
        self.assertEqual(0, ctx.game_interface.read_calls)


if __name__ == "__main__":
    unittest.main()
