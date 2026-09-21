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
    config_sha256="a799e9101032bbc086e47baa06cb54b38c96bd553c4259b8c07e39777c25be9a",
    options=presets.merge(presets.NO_RANDO_OPTIONS, {"death_link": True}),
    start_inventory=dict(presets.ALL_ITEMS_START),
    companions=[
        SlotSpec(
            name="DeathLinkPartner",
            game="Metroid Prime 2: Echoes",
            options={"death_link": True},
        )
    ],
    steps=[
        Step(
            "In the client chat, run `/test_deathlink outgoing`.",
            "The other slot dies.",
        ),
        Step(
            "Run `/test_deathlink incoming`.",
            "You die in-game.",
        ),
        Step(
            "Cause a *real* death (stand in Dark Aether without a suit).",
            "The other slot dies. No death loop: receiving a death while already dead or during the "
            "death animation does not re-broadcast.",
        ),
    ],
    pass_criteria=[
        "Outgoing and incoming test deaths both work.",
        "A real in-game death is sent exactly once.",
        "No death loop (the incoming death is not echoed back out).",
    ],
    on_failure=[
        "`client/death_link.py::death_link_check`",
        "`client/client.py::on_deathlink` / `_handle_check_deathlink`",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
