"""MT14 -- spring ball: the ComputeBallMovement hook and its gates."""

from __future__ import annotations

from . import harness, presets
from .harness import ManualTest, Step, Variant

TEST = ManualTest(
    slug="mt14_spring_ball",
    title="Spring Ball: bomb jump on C-Stick up once bombs are owned",
    priority="P1",
    proves="the button jumps on the ground only, keeps rolling momentum, and leaves vanilla bomb jumps alone",
    seed=1_000_014,
    config_sha256="2bf185ceb91e115c0b6087a43d1a85314dc69f299c6eab91efbd8b395b00d836",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"spring_ball": True, "spring_ball_button": "c_stick_up"},
    ),
    start_inventory=dict(presets.ALL_ITEMS_START),
    steps=[
        Step(
            "In Landing Site, morph and tap C-Stick up while resting on flat ground.",
            "The ball hops as high as a single bomb jump, with the bomb-jump sound and rumble but no bomb.",
        ),
        Step(
            "Roll forward at full speed and tap C-Stick up.",
            "The ball jumps and keeps rolling forward through the jump instead of stopping dead.",
            why="BombJump zeroes horizontal velocity; the cave restores it.",
        ),
        Step(
            "Hold C-Stick up.",
            "The ball jumps again each time it lands, with a short pause (about 2/3 s) between jumps.",
        ),
        Step(
            "Jump, and tap C-Stick up again at the top of the jump.",
            "Nothing happens in mid-air.",
        ),
        Step(
            "Lay a bomb and bomb jump, then do a double bomb jump.",
            "Both behave exactly as in vanilla.",
        ),
        Step(
            "Charge a Boost Ball and tap C-Stick up before releasing.",
            "The ball jumps and the boost charge is cancelled (vanilla bomb-jump behavior).",
        ),
        Step(
            "Unmorph and tap C-Stick up.",
            "Only the vanilla first-person C-Stick action happens; no jump.",
        ),
        Step(
            "Find a Spider Ball track, attach to it (hold R) and tap C-Stick up.",
            "No spring while attached. Releasing R and resting on the ground, it works again.",
        ),
    ],
    variants={
        "no_bombs": Variant(
            config_sha256="799df14cc02d32f6aa30b965b7c6eb4e15c210d929baf10fe8a71a5fba895ef1",
            start_inventory={"Morph Ball Bomb": 0},
            steps=[
                Step(
                    "Morph in Landing Site and tap / hold C-Stick up on the ground.",
                    "Nothing happens: spring ball needs Morph Ball Bombs.",
                )
            ],
        ),
        "off": Variant(
            config_sha256="ffef5bbc4ab7a635b43b9ab973951031d40e4bbfaedc402e3f197e3de7019dec",
            options={"spring_ball": False},
            steps=[
                Step(
                    "Morph in Landing Site and tap / hold C-Stick up on the ground.",
                    "Nothing happens: with `spring_ball: false` the hook is never installed.",
                )
            ],
        ),
        "d_pad_up": Variant(
            config_sha256="a014ced7c0cf47cef63b72b68d4a009e7faec877b98db89c2cb60fd7a09bea99",
            options={"spring_ball_button": "d_pad_up"},
            steps=[
                Step(
                    "Morph in Landing Site and tap C-Stick up, then D-Pad up.",
                    "C-Stick up does nothing; D-Pad up jumps.",
                )
            ],
        ),
    },
    pass_criteria=[
        "The button jumps only on the ground, only in Morph Ball, and only with bombs.",
        "Rolling momentum survives the jump.",
        "Holding the button repeats after a short cooldown, never several times per landing.",
        "Laid bombs and Boost Ball behave exactly as in vanilla.",
        "`--variant no_bombs` and `--variant off` never jump; `--variant d_pad_up` jumps on D-Pad up only.",
    ],
    on_failure=[
        "`client/spring_ball_patch.py`",
        "`client/versions.py::SpringBallAddresses`",
        "`tools/find_spring_ball_addresses.py` (re-derive the addresses for this build)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
