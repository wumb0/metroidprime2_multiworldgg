"""MT16 -- translator lore hints: hologram text and scan-triggered hints (PLAN.md section R)."""

from __future__ import annotations

from ...item_pool import STK_ITEM_NAMES
from . import harness, presets
from .harness import ManualTest, Step, Variant

_SLUG = "mt16_translator_lore_hints"

TEST = ManualTest(
    slug=_SLUG,
    title="Translator lore hints: holograms name progression items and send hints when translated",
    priority="P1",
    proves=(
        "each colored lore hologram names a progression item's real location, and only a completed, "
        "translated scan sends that hint"
    ),
    seed=1_000_016,
    config_sha256="995ce7020bae1b49091e7878a8297feec23c6ff42dc99fd422b2a5b46989b922",
    starting_room="Temple Grounds/Meeting Grounds/Door to Service Access",
    options=presets.merge(
        presets.NO_RANDO_OPTIONS,
        presets.MAP_OPTIONS,
        presets.FAST_RETRY_OPTIONS,
        {"translator_lore_hints": "my_items"},
    ),
    # Everything (all four translators included) except the Sky Temple Keys,
    # which would otherwise just be more own-item copies in the pool.
    start_inventory={**presets.ALL_ITEMS_START, **dict.fromkeys(STK_ITEM_NAMES, 0)},
    companions=[presets.filler_slot(1)],
    setup=[
        (
            "Host the generated multiworld and connect the MP2 client **and** the Filler1 (Clique) slot "
            "with a text client, so hint messages are visible from both sides."
        ),
        "Open the spoiler's **Translator Lore Hints** block: it lists the expected text for every hologram.",
    ],
    notes=[
        (
            "Violet holograms by distance from the start: Meeting Grounds (start room), Path of Eyes (2 rooms), "
            "Great Temple - Main Energy Controller (6), Transport to Agon Wastes and Fortress Transport Access (7)."
        ),
    ],
    steps=[
        Step(
            "Connect the client and wait a few seconds without scanning anything.",
            "No lore hints are sent.",
        ),
        Step(
            "Scan the Meeting Grounds hologram about half way, then look away.",
            "No hint is sent.",
            why="Only a finished scan (progress 255) counts.",
        ),
        Step(
            "Scan the Meeting Grounds hologram to completion.",
            (
                "The text matches the spoiler's Meeting Grounds line (\"Your <item> can be found in ... .\", "
                "colored). The client logs `Hint scan complete` and one priority hint for that item appears "
                "in both clients."
            ),
        ),
        Step(
            "Scan the Path of Eyes hologram and one or two more Violet holograms.",
            "Each matches its spoiler line and sends exactly one hint.",
        ),
        Step(
            "Open the Logbook entry for one of them.",
            "The body shows the same hint text.",
        ),
        Step(
            "Scan a Sky Temple Key pillar or any other non-lore scan (e.g. an enemy).",
            "No lore hint is sent for it.",
        ),
        Step(
            "Restart the MP2 client and reconnect.",
            "No duplicate hint messages.",
        ),
    ],
    variants={
        "any": Variant(
            # Searched so Filler1's only progression item lands on a Violet
            # hologram near the start (only base seeds must be unique).
            seed=1_000_021,
            config_sha256="07d0c4e73aa19e21a31e82ccaaab1c93399f23219e062419b57da91e0379b9e8",
            options={"translator_lore_hints": "any"},
            notes=[
                (
                    "Temple Grounds - Transport to Agon Wastes names Filler1's Feeling of Satisfaction (in your "
                    "Agon Wastes: Storage B). Every other line is in the spoiler."
                ),
            ],
            steps=[
                Step(
                    (
                        "Go to Temple Grounds - Transport to Agon Wastes (7 rooms from the start; use the map) "
                        "and scan its hologram."
                    ),
                    (
                        "Text reads \"Filler1's Feeling of Satisfaction can be found in your Agon Wastes: Storage B "
                        '- Pickup (Missile)." The hint appears with an *unspecified* status (not priority), and '
                        "the client logs no error."
                    ),
                    why="The server only accepts HINT_UNSPECIFIED for another player's item.",
                ),
                Step(
                    "Scan the Meeting Grounds hologram (one of your own items).",
                    "It still arrives as a priority hint.",
                ),
            ],
            pass_criteria=[
                "Foreign-item hints arrive as unspecified and own-item hints as priority, with no rejected packet."
            ],
        ),
        "lore_colors": Variant(
            config_sha256="9d618e0f8dd694be580433b9c696c74d7c20851c8c73276b205ed86d325dac79",
            options={"translator_lore_rando": "full_random"},
            notes=[
                (
                    "The spoiler's **Translator Lore Colors** block lists each hologram's color. In this seed "
                    "Meeting Grounds and Path of Eyes (vanilla Violet) are both Amber."
                ),
            ],
            steps=[
                Step(
                    "Look at the Meeting Grounds hologram before scanning it.",
                    "The hologram and its glow are Amber, not Violet.",
                ),
                Step(
                    "Scan it to completion, then do the same in Path of Eyes.",
                    "Each translates, shows its hint, and sends it (every translator is in the starting inventory).",
                ),
            ],
            pass_criteria=["Every checked hologram looks like, and opens with, its spoiler color."],
        ),
        "off": Variant(
            config_sha256="4b074402645f12886755691e1faca639ec2ddbb5548527a43943f29b9255667a",
            options={"translator_lore_hints": "off"},
            steps=[
                Step(
                    "Translate the Meeting Grounds hologram.",
                    "The vanilla Luminoth lore text appears. No hint is sent.",
                )
            ],
            pass_criteria=["Holograms keep vanilla lore and never send hints."],
        ),
    },
    pass_criteria=[
        "Every scanned hologram's text matches its spoiler line and names a progression item.",
        "A partial scan sends nothing; a completed scan sends exactly one hint.",
        "Client restarts don't duplicate hints.",
    ],
    on_failure=[
        "`hint_scans.py` (`TRANSLATOR_LORE_HINT_SCANS`, `translator_lore_hint_locations`)",
        "`patch_data.py::_translator_lore_string_changes`",
        "`client/client.py::_handle_hint_scans` (per-(player, status) grouping)",
    ],
)

if __name__ == "__main__":
    harness.cli(TEST)
