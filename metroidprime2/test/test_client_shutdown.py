"""Regression tests for ``client/client.py``'s shutdown path: closing the
client must not hang on a server connect that's still pending, or on the
Dolphin sync loop's tick delay."""

from __future__ import annotations

import asyncio
import os
import time
import unittest

# See test_deathlink.py for why these two lines must run before importing
# client.client.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

import worlds

if "network_data_package" not in worlds.__dict__:
    worlds.network_data_package = {"games": {}}
    worlds.network_data_package_single_game = {}

from ..client.client import MetroidPrime2Context, _shutdown, _sleep_unless_exiting


def _bare_context() -> MetroidPrime2Context:
    ctx = object.__new__(MetroidPrime2Context)
    ctx.exit_event = asyncio.Event()
    ctx.dolphin_sync_task = None
    ctx.server = None
    ctx.server_task = None
    return ctx


class TestClientShutdown(unittest.TestCase):
    def test_sleep_returns_early_on_exit(self) -> None:
        async def run() -> float:
            ctx = _bare_context()
            asyncio.get_running_loop().call_later(0.05, ctx.exit_event.set)
            start = time.monotonic()
            await _sleep_unless_exiting(ctx, 10)
            return time.monotonic() - start

        self.assertLess(asyncio.run(run()), 1)

    def test_pending_server_connect_is_cancelled(self) -> None:
        async def run() -> tuple[float, bool]:
            ctx = _bare_context()
            # Stands in for server_loop stuck in websockets' connect timeout.
            ctx.server_task = asyncio.create_task(asyncio.sleep(60))
            pending = ctx.server_task

            async def shutdown() -> None:
                # CommonContext.shutdown() awaits server_task.
                if ctx.server_task:
                    await ctx.server_task

            ctx.shutdown = shutdown  # type: ignore[method-assign]
            ctx.exit_event.set()
            start = time.monotonic()
            await _shutdown(ctx)
            return time.monotonic() - start, pending.cancelled()

        elapsed, cancelled = asyncio.run(run())
        self.assertLess(elapsed, 1)
        self.assertTrue(cancelled)


if __name__ == "__main__":
    unittest.main()
