"""MT12 -- client/session lifecycle and commands."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt12_session_lifecycle",
    title="Session lifecycle and client commands",
    priority="P2",
    proves="menu/new game/load/wrong-seed/reconnect/export_iso all behave",
    seed=1_000_012,
    config_sha256="70e850c5fe0498aaa63dac5ad719d8838396202aae1be4e425a6a5c625ff30a7",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS),
    variants={
        # A second build of a *different* seed, for the wrong-seed check.
        "other": Variant(
            seed=1_000_112,
            config_sha256="dc0e02e0cd6052efbe1503aea8e9cb4d2db2ae61d80636c0aa83cafdda0ee3a8",
        ),
    },
    steps=[
        Step(
            "Connect the client while Dolphin is at the main menu.",
            "The client reports `IN_MENU`.",
        ),
        Step("Start a New Game.", "The client reports `IN_GAME`."),
        Step(
            "Load the *other* seed's ISO (`--variant other`) with this client still connected.",
            "The client reports `WRONG_SEED`.",
        ),
        Step(
            "Stop and restart emulation, then run `/reconnect`.",
            "The client reconnects and reports the current state.",
        ),
        Step(
            "Run `/export_iso` with the game closed.",
            "The existing ISO is deleted and re-patched.",
        ),
        Step(
            "Run `/export_iso` with the game open.",
            "The client refuses with an error.",
        ),
        Step(
            "Run `/status`, `/test_hud hello`, and `/mp2_debug_inventory`.",
            "`/status` prints the connection state; `/test_hud` shows a HUD memo; the inventory dump "
            "lists non-empty slots.",
        ),
    ],
    pass_criteria=[
        "Every command behaves as listed.",
        "Wrong-seed detection fires.",
        "`/export_iso` refuses while connected and re-patches while disconnected.",
    ],
    on_failure=[
        "`client/client.py` (`MetroidPrime2CommandProcessor`, `update_connection_status`)",
        "`client/game_interface.py` (`get_connection_state`)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
