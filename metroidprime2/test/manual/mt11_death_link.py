"""MT11 -- Death Link both directions in a live game."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, SlotSpec, Step

TEST = ManualTest(
    slug="mt11_death_link",
    title="Death Link: both directions, no loop",
    priority="P1",
    proves="Death Link works in both directions in a live game without a death loop",
    seed=1_000_011,
    config_sha256="0b898386099c6569987bd461b938d91f2f6010c93b8fc443e2a299a732c65a7d",
    options=presets.merge(presets.NO_RANDO_OPTIONS, presets.MAP_OPTIONS, {"death_link": True}),
    start_inventory=dict(presets.ALL_ITEMS_START),
    companions=[
        SlotSpec(
            name="DeathLinkPartner",
            game="Metroid Prime 2: Echoes",
            options=presets.merge(presets.MAP_OPTIONS, {"death_link": True}),
        )
    ],
    steps=[
        Step(
            "Cause a *real* death (stand in Dark Aether without a suit).",
            "The other slot dies, and the death is sent exactly once.",
        ),
        Step(
            "Have the DeathLinkPartner slot die in its own game.",
            "You die in-game.",
        ),
        Step(
            "Watch the partner slot after your death from the previous step.",
            "No death loop: receiving a death while already dead or during the death animation "
            "does not re-broadcast, so the partner is not killed a second time.",
        ),
    ],
    pass_criteria=[
        "A real in-game death is sent to the partner exactly once.",
        "A death from the partner kills you in-game.",
        "No death loop (the incoming death is not echoed back out).",
    ],
    on_failure=[
        "`client/death_link.py::death_link_check`",
        "`client/client.py::on_deathlink` / `_handle_check_deathlink`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
