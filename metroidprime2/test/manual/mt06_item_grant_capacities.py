"""MT06 -- cross-computed capacities (ammo, launcher, progressives) in-game."""

from __future__ import annotations

from ... import constants
from ...client.receive_items import compute_desired_capacities
from ...locations import LOCATION_TABLE
from . import harness, presets
from .harness import ManualTest, Step, Variant

# The 14 independent rooms, in the order the tester collects them. Three
# Missile Expansions come before the launcher on purpose (capacity without a
# usable weapon), then the cross-computed Power Bomb/Energy Tank/progressive
# items, then one ammo expansion.
_ORDER: list[tuple[int, str]] = [
    (0, "Missile Expansion"),
    (2, "Missile Expansion"),
    (12, "Missile Expansion"),
    (1, "Missile Launcher"),
    (13, "Power Bomb Expansion"),
    (14, "Power Bomb Expansion"),
    (8, "Power Bomb"),
    (9, "Energy Tank"),
    (4, "Energy Tank"),
    (5, "Progressive Suit"),
    (6, "Progressive Suit"),
    (20, "Progressive Grapple"),
    (21, "Progressive Grapple"),
]

# Items this test manipulates directly. Everything *else* is precollected, so
# the plando bench can't starve the main fill of the world-opening
# progression it needs (with the launcher/Power-Bomb unlock options off, a
# bench locked into the near-start rooms otherwise makes this seed
# systematically unfillable -- verified). The subject (capacities arriving
# from pickups) is unaffected: these items are still collected in-game, not
# precollected.
_TESTABLE_ITEMS: frozenset[str] = frozenset(
    {
        "Missile Expansion",
        "Missile Launcher",
        "Power Bomb Expansion",
        "Power Bomb",
        "Energy Tank",
        "Progressive Suit",
        "Progressive Grapple",
        "Dark Ammo Expansion",
        "Light Ammo Expansion",
        "Beam Ammo Expansion",
    }
)

_BASE_START_INVENTORY: dict[str, int] = {
    name: count for name, count in presets.ALL_ITEMS_START.items() if name not in _TESTABLE_ITEMS
}


def _ammo_item(split_beam_ammo: bool) -> str:
    return "Dark Ammo Expansion" if split_beam_ammo else "Beam Ammo Expansion"


def _plando(split_beam_ammo: bool) -> list[dict]:
    plan = [*_ORDER, (22, _ammo_item(split_beam_ammo))]
    return [
        {"item": item, "location": LOCATION_TABLE[index].name, "from_pool": True}
        for index, item in plan
    ]


def _received_prefix() -> list[tuple[str, int]]:
    received: list[tuple[str, int]] = []
    for name, count in _BASE_START_INVENTORY.items():
        received.extend((name, 1) for _ in range(count))
    return received


def _expected_notes(split_beam_ammo: bool, unlock_launcher: bool, unlock_power_bombs: bool) -> list[str]:
    """Capacity table derived from the client's own
    ``compute_desired_capacities`` so the table and the code can't disagree."""
    plan = [*_ORDER, (22, _ammo_item(split_beam_ammo))]
    received = _received_prefix() + [(name, 1) for name in constants.DEFAULT_STARTING_ITEMS]
    lines: list[str] = [
        "baseline (precollected + defaults): "
        + ", ".join(
            f"item {key}={value}"
            for key, value in sorted(
                compute_desired_capacities(received, 0, unlock_launcher, unlock_power_bombs).items()
            )
            if value
        )
    ]
    for step_index, (index, item) in enumerate(plan, start=1):
        received.append((item, 1))
        desired = compute_desired_capacities(received, 0, unlock_launcher, unlock_power_bombs)
        nonzero = {key: value for key, value in desired.items() if value}
        rendered = ", ".join(f"item {key}={value}" for key, value in sorted(nonzero.items()))
        lines.append(f"after step {step_index} (`{item}` at `{LOCATION_TABLE[index].name}`): {rendered}")
    return lines


def _steps(ammo_item: str) -> list[Step]:
    return [
        Step(
            "Connect the client before collecting anything.",
            "Baseline inventory matches the table's baseline row.",
        ),
        Step(
            "Collect the 14 pickups in the printed order, running `/mp2_debug_inventory` after each.",
            "After each pickup, the item amounts/capacities match the script's expected table. In "
            "this variant the Missile Expansions before the launcher raise the capacity but leave "
            "0 usable missiles until the launcher is collected.",
        ),
        Step(
            f"From the server console, run `/send <player> {ammo_item}`.",
            "The corresponding ammo capacity goes up by exactly one expansion's worth, not to a "
            "stranded raw value.",
        ),
    ]


def _variant(
    split_beam_ammo: bool, unlock_launcher: bool, unlock_power_bombs: bool, config_sha256: str
) -> Variant:
    return Variant(
        options={
            "missile_expansions_unlock_launcher": unlock_launcher,
            "power_bomb_expansions_unlock_power_bombs": unlock_power_bombs,
            "split_beam_ammo": split_beam_ammo,
        },
        start_inventory=dict(_BASE_START_INVENTORY),
        plando=_plando(split_beam_ammo),
        notes=_expected_notes(split_beam_ammo, unlock_launcher, unlock_power_bombs),
        steps=_steps(_ammo_item(split_beam_ammo)),
        config_sha256=config_sha256,
    )


TEST = ManualTest(
    slug="mt06_item_grant_capacities",
    title="Item grants: cross-computed capacities land correctly in-game",
    priority="P0",
    proves="cross-computed capacities (ammo, launcher, progressives) land correctly in the live inventory",
    seed=1_000_006,
    options={
        "progressive_suit": True,
        "progressive_grapple": True,
        "energy_per_tank": 250,
    },
    notes=[
        (
            "Non-tested items are granted via `start_inventory` so the plando bench can't make "
            "the seed unfillable; the tested items below are all collected in-game."
        ),
    ],
    steps=[
        Step(
            "Build both variants side by side (`--variant a` and `--variant b`).",
            "See the two variant sections below for each one's collection order and expected "
            "capacity table.",
        )
    ],
    variants={
        "a": _variant(
            split_beam_ammo=True,
            unlock_launcher=False,
            unlock_power_bombs=False,
            config_sha256="aaf3f1672610b083ac1e4e941ebcf2af73e00495edcac7a9f6c5048bc5c5f8a7",
        ),
        "b": _variant(
            split_beam_ammo=False,
            unlock_launcher=True,
            unlock_power_bombs=True,
            config_sha256="899657cf8ae7b8bd00ea62dd2be2b5f1d8d6dc966ed5361c1b39be7758864242",
        ),
    },
    pass_criteria=[
        "Variant a: expansions before the launcher grant capacity but no usable missiles until the launcher.",
        "Variant b: expansions unlock their weapon immediately.",
        "Progressive Suit grants Dark Suit then Light Suit; Progressive Grapple grants Grapple then Screw Attack.",
        "Energy Tanks are worth 250 each.",
        "The server-console expansion pushes capacity up by exactly one expansion.",
    ],
    on_failure=[
        "`client/receive_items.py` (`compute_desired_capacities`/`plan_grants`)",
        "`client/client.py::_handle_grant_items`",
        "`patch_data.starting_items_config` (starting capacities)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
