#!/usr/bin/env python3
"""Vendor randovania's prime2_opr logic/pickup databases into this world's
data/, and (re)generate options_tricks.py from the trick resource database.

``prime2_opr`` (not the plain ``prime2`` game definition) is the one that
actually matches what open-prime-rando's patcher does to the ISO: OPR
applies several hardcoded, always-on "rebalance" patches that move or
re-gate specific vanilla objects (e.g.
``open_prime_rando.echoes.specific_area_patches.rebalance_patches.
hive_access_tunnel_translator_gate``, which physically relocates the Hive
Access Tunnel translator gate to guard the Hive Chamber A hole instead of
the corridor to Hive Transport Area, regardless of ``translator_gate_rando``).
Vendoring from plain ``prime2`` silently disagreed with the real, patched
topology for every room such a patch touches -- caught empirically via an
in-game softlock at the very start of a fresh game (fully vanilla options).

This script is excluded from built .apworld archives (see ../.apignore) and
is never imported at runtime; it only needs to run in a randovania dev
checkout, not in a MultiWorldGG install.

Usage:
    python tools/sync_randovania_data.py [--randovania-root PATH]

By default ``--randovania-root`` is ``../randovania`` relative to this
world's package directory (i.e. a sibling checkout next to metroidprime2/
in the repo root).
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from pathlib import Path
from typing import Any

WORLD_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RANDOVANIA_ROOT = WORLD_ROOT.parent / "randovania"

EXPECTED_SCHEMA_VERSION = 34
EXPECTED_GAME = "prime2_opr"
EXPECTED_PICKUP_NODE_COUNT = 119

EXPECTED_TRANSLATOR_GATE_COUNT = 17

# randovania's LayoutTranslatorRequirement -> the vendored DB item short name
# this world's logic/patch data uses for that gate. "removed" ("Unlocked" in
# randovania's UI) is a real, distinct requirement -- Scan Visor only, no
# translator item at all -- which this world represents as ``None``.
# See randovania/games/prime2/layout/translator_configuration.py's ITEM_NAMES.
TRANSLATOR_REQUIREMENT_NAMES: dict[str, str | None] = {
    "violet": "Violet",
    "amber": "Amber",
    "emerald": "Emerald",
    "cobalt": "Cobalt",
    "removed": None,
}

LEVEL_NAMES = {1: "beginner", 2: "intermediate", 3: "advanced", 4: "expert", 5: "ludicrous"}
_TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------
# Generic strip helpers
# --------------------------------------------------------------------------

def _strip_requirement_comments(obj: Any) -> None:
    """Recursively null out every requirement ``data.comment``, in place."""
    if isinstance(obj, dict):
        if obj.get("type") in ("and", "or") and isinstance(obj.get("data"), dict):
            data = obj["data"]
            if "comment" in data:
                data["comment"] = None
        for value in obj.values():
            _strip_requirement_comments(value)
    elif isinstance(obj, list):
        for item in obj:
            _strip_requirement_comments(item)


def _blank_keys(obj: Any, replacements: dict[str, Any]) -> None:
    """Recursively replace the value of any dict key found in ``replacements``
    with its configured blank value (a fresh copy, since values are mutable).
    """
    if isinstance(obj, dict):
        for key, blank in replacements.items():
            if key in obj:
                obj[key] = copy.deepcopy(blank)
        for value in obj.values():
            _blank_keys(value, replacements)
    elif isinstance(obj, list):
        for item in obj:
            _blank_keys(item, replacements)


def _strip_header(header: dict) -> None:
    header["minimal_logic"] = None
    header["hint_feature_database"] = {}
    for dock_type in header["dock_type_database"]["types"].values():
        dock_type["weakness_distributor"] = None
    _strip_requirement_comments(header)


def _strip_region(doc: dict) -> None:
    for area in doc["areas"].values():
        if "hint_features" in area:
            area["hint_features"] = []
        for node in area["nodes"].values():
            if "description" in node:
                node["description"] = ""
            if "hint_features" in node:
                node["hint_features"] = []
    _strip_requirement_comments(doc)


def _strip_pickup_database(doc: dict) -> None:
    _blank_keys(doc, {"offworld_models": {}, "hint_features": []})


def _write_compact(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    return re.sub(r" +", " ", text).strip()


# --------------------------------------------------------------------------
# options_tricks.py generation
# --------------------------------------------------------------------------

def generate_options_tricks(header: dict, out_path: Path) -> int:
    tricks: dict[str, dict] = header["resource_database"]["tricks"]
    used_trick_levels: dict[str, list[int]] = header.get("used_trick_levels", {})

    lines = [
        '"""Trick difficulty options, generated by tools/sync_randovania_data.py',
        "from resource_database.tricks in the randovania prime2 logic database.",
        "",
        "Do not edit by hand -- re-run the sync script instead.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from Options import Choice",
        "",
        "",
    ]

    names_entries: list[tuple[str, str]] = []
    classes_entries: list[tuple[str, str]] = []

    for short_name in sorted(tricks):
        trick = tricks[short_name]
        long_name = trick["long_name"]
        description = _strip_html(trick.get("description") or "")
        levels = used_trick_levels.get(short_name, [])
        level_names = ", ".join(LEVEL_NAMES[level] for level in levels) if levels else "none"

        class_name = f"Trick{short_name}"
        attr_name = f"trick_{short_name.lower()}"

        doc_body = [long_name]
        if description:
            doc_body.append("")
            doc_body.append(description)
        doc_body.append("")
        doc_body.append(f"Used difficulty levels in logic: {level_names}.")
        docstring = "\n    ".join(doc_body)

        lines.append(f"class {class_name}(Choice):")
        lines.append(f'    """{docstring}')
        lines.append('    """')
        lines.append(f'    display_name = "Trick: {long_name}"')
        lines.append("    option_use_global = 0")
        lines.append("    option_disabled = 1")
        lines.append("    option_beginner = 2")
        lines.append("    option_intermediate = 3")
        lines.append("    option_advanced = 4")
        lines.append("    option_expert = 5")
        lines.append("    option_ludicrous = 6")
        lines.append("    default = 0")
        lines.append("")
        lines.append("")

        names_entries.append((short_name, attr_name))
        classes_entries.append((short_name, class_name))

    lines.append("TRICK_OPTION_NAMES: dict[str, str] = {")
    for short_name, attr_name in names_entries:
        lines.append(f"    {short_name!r}: {attr_name!r},")
    lines.append("}")
    lines.append("")
    lines.append("TRICK_OPTION_CLASSES: dict[str, type] = {")
    for short_name, class_name in classes_entries:
        lines.append(f"    {short_name!r}: {class_name},")
    lines.append("}")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return len(tricks)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def generate_vanilla_translator_gates(
    randovania_root: Path, gate_node_names: set[str], out_path: Path
) -> int:
    """Vendor the *vanilla* translator gate requirements from randovania's own
    shipped ``prime2_opr`` starter preset.

    This can NOT be derived from the logic database's per-gate
    ``extra.vanilla_actual``/``extra.vanilla_color`` fields. Those describe the
    unpatched retail game, and open-prime-rando's patched game differs: with the
    Hive Access Tunnel gate relocated to guard the Hive Chamber A hole (OPR's
    ``hive_access_tunnel_translator_gate`` rebalance patch), the Hive Transport
    Area and Industrial Site gates would make the whole Temple Grounds start
    unescapable, so randovania's prime2_opr preset ships them as "removed"
    (Unlocked) instead of the retail Violet. That preset is the shipped,
    generator-verified-solvable definition of "vanilla" for this game, exactly
    as ``randovania.games.prime2.layout.translator_configuration.
    TranslatorConfiguration.from_json`` reads it.

    Writes ``{"<Region>/<Area>/<Node>": "<Color>" | null}`` for all 17 gates.
    """
    preset = json.loads(
        (randovania_root / "randovania" / "games" / EXPECTED_GAME / "presets" / "starter_preset.rdvpreset").read_text(
            encoding="utf-8"
        )
    )
    assert preset["game"] == EXPECTED_GAME, f"expected preset game {EXPECTED_GAME!r}, got {preset['game']!r}"
    raw = preset["configuration"]["translator_configuration"]["translator_requirement"]

    assert set(raw) == gate_node_names, (
        "starter preset translator gates disagree with the vendored logic database: "
        f"preset-only={sorted(set(raw) - gate_node_names)} db-only={sorted(gate_node_names - set(raw))}"
    )
    assert len(raw) == EXPECTED_TRANSLATOR_GATE_COUNT, (
        f"expected {EXPECTED_TRANSLATOR_GATE_COUNT} translator gates, got {len(raw)}"
    )

    result: dict[str, str | None] = {}
    for node_name, requirement in sorted(raw.items()):
        assert requirement in TRANSLATOR_REQUIREMENT_NAMES, (
            f"{node_name}: starter preset has non-vanilla translator requirement {requirement!r}"
        )
        result[node_name] = TRANSLATOR_REQUIREMENT_NAMES[requirement]

    _write_compact(out_path, result)
    return len(result)


def main(randovania_root: Path, out_dir: Path | None = None) -> None:
    out_dir = out_dir or (WORLD_ROOT / "data")
    logic_db_src = randovania_root / "randovania" / "games" / "prime2_opr" / "logic_database"
    pickup_db_src = (
        randovania_root / "randovania" / "games" / "prime2_opr" / "pickup_database" / "pickup-database.json"
    )

    header = json.loads((logic_db_src / "header.json").read_text(encoding="utf-8"))
    assert header["schema_version"] == EXPECTED_SCHEMA_VERSION, (
        f"expected schema_version {EXPECTED_SCHEMA_VERSION}, got {header['schema_version']}"
    )
    assert header["game"] == EXPECTED_GAME, f"expected game {EXPECTED_GAME!r}, got {header['game']!r}"

    region_files: list[str] = header["regions"]

    out_logic_dir = out_dir / "logic_database"
    out_logic_dir.mkdir(parents=True, exist_ok=True)

    total_nodes = 0
    total_pickups = 0
    total_events = 0
    event_names: set[str] = set()
    gate_node_names: set[str] = set()

    header_copy = copy.deepcopy(header)
    _strip_header(header_copy)
    _write_compact(out_logic_dir / "header.json", header_copy)

    for region_file in region_files:
        doc = json.loads((logic_db_src / region_file).read_text(encoding="utf-8"))
        for area_name, area in doc["areas"].items():
            for node_name, node in area["nodes"].items():
                total_nodes += 1
                node_type = node["node_type"]
                if node_type == "pickup":
                    total_pickups += 1
                elif node_type == "event":
                    total_events += 1
                    event_names.add(node["event_name"])
                elif node_type == "configurable_node":
                    gate_node_names.add(f"{doc['name']}/{area_name}/{node_name}")

        region_copy = copy.deepcopy(doc)
        _strip_region(region_copy)
        _write_compact(out_logic_dir / region_file, region_copy)

    assert total_pickups == EXPECTED_PICKUP_NODE_COUNT, (
        f"expected {EXPECTED_PICKUP_NODE_COUNT} pickup nodes, got {total_pickups}"
    )

    pickup_db = json.loads(pickup_db_src.read_text(encoding="utf-8"))
    _strip_pickup_database(pickup_db)
    _write_compact(out_dir / "pickup_database.json", pickup_db)

    try:
        version = subprocess.run(
            ["git", "-C", str(randovania_root), "describe", "--tags"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        version = "unknown"
    (out_dir / "RANDOVANIA_VERSION.txt").write_text(version + "\n", encoding="utf-8")

    gate_count = generate_vanilla_translator_gates(
        randovania_root, gate_node_names, out_dir / "vanilla_translator_gates.json"
    )

    trick_count = generate_options_tricks(header, WORLD_ROOT / "options_tricks.py")

    print(f"randovania root: {randovania_root}")
    print(f"randovania version: {version}")
    print(f"regions: {len(region_files)}")
    print(f"nodes: {total_nodes}")
    print(f"pickup nodes: {total_pickups}")
    print(f"event nodes: {total_events} ({len(event_names)} distinct event names)")
    print(f"translator gates: {gate_count}")
    print(f"tricks: {trick_count}")
    print(f"requirement templates: {len(header['resource_database']['requirement_template'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--randovania-root",
        type=Path,
        default=DEFAULT_RANDOVANIA_ROOT,
        help="Path to a randovania checkout (default: %(default)s)",
    )
    args = parser.parse_args()
    main(args.randovania_root.resolve())
