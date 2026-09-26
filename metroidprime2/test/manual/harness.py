"""Build pipeline for the manual (in-game) tests (PLAN.md M4).

A manual test is a python module under this package that defines exactly one
module-level ``TEST = ManualTest(...)`` and ends with::

    if __name__ == "__main__":
        harness.cli(TEST)

Running that module builds a purpose-made ISO for the test: a fixed seed, a
fixed set of options, an optional forced starting room, and (optionally) a
small ``plando_items`` bench that places specific items in rooms that don't
depend on one another. The generated ``.apmp2``'s ``config.json`` is hashed
against ``TEST.config_sha256`` so a rebuild months later either produces the
same patch data or fails loudly.

See ``MANUAL_TEST_PLAN.md`` sections 3 and 4 for the design this implements.
Everything here runs in MultiWorldGG's own interpreter (its venv), e.g.::

    cd MultiWorldGG
    SKIP_REQUIREMENTS_UPDATE=1 .venv/bin/python \
        -m worlds.metroidprime2.test.manual.mt01_smoke_vanilla --iso ~/isos/echoes.iso
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Importing Generate/Main (below, lazily) triggers MultiWorldGG's
# ModuleUpdate machinery, which otherwise shells out to pip for every other
# world's requirements.txt. Same guard as the repo-level conftest.py.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_BASE = REPO_ROOT / "manual_tests"
PRIMARY_GAME = "Metroid Prime 2: Echoes"


# --------------------------------------------------------------------------
# Spec objects (MANUAL_TEST_PLAN.md section 3.1)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    do: str
    expect: str
    why: str = ""


@dataclass(frozen=True)
class SlotSpec:
    name: str
    game: str
    options: dict[str, Any] = field(default_factory=dict)
    start_inventory: dict[str, int] = field(default_factory=dict)
    plando: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Variant:
    """Overrides applied on top of a ``ManualTest`` for ``--variant <name>``.

    Only the fields a variant actually changes need to be set; everything
    else falls back to the base test. ``config_sha256`` here overrides the
    base test's pin for this variant (a variant with different options
    necessarily produces different patch data)."""

    options: dict[str, Any] = field(default_factory=dict)
    start_inventory: dict[str, int] = field(default_factory=dict)
    plando: list[dict[str, Any]] | None = None
    seed: int | None = None
    starting_room: str | None = None
    companions: list[SlotSpec] | None = None
    steps: list[Step] | None = None
    pass_criteria: list[str] | None = None
    notes: list[str] | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class ManualTest:
    slug: str
    title: str
    priority: str  # "P0" | "P1" | "P2"
    proves: str
    seed: int
    options: dict[str, Any] = field(default_factory=dict)
    start_inventory: dict[str, int] = field(default_factory=dict)
    plando: list[dict[str, Any]] = field(default_factory=list)
    starting_room: str | None = None
    companions: list[SlotSpec] = field(default_factory=list)
    setup: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    pass_criteria: list[str] = field(default_factory=list)
    on_failure: list[str] = field(default_factory=list)
    config_sha256: str | None = None
    variants: dict[str, Variant] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Extra CLI flags to show in the README/INSTRUCTIONS build command (e.g.
    # "--pal" for MT13). Not part of the spec's option/plando data.
    build_flags: str = ""
    # Sidecar files the build writes into its output dir, e.g. a paste-ready
    # block of server-console commands. name -> lines, rendered as a fenced
    # block in the README/INSTRUCTIONS and written verbatim by build().
    artifacts: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedTest:
    """A ``ManualTest`` with a named variant's overrides applied."""

    slug: str
    build_id: str
    title: str
    priority: str
    proves: str
    seed: int
    options: dict[str, Any]
    start_inventory: dict[str, int]
    plando: list[dict[str, Any]]
    starting_room: str | None
    companions: list[SlotSpec]
    setup: list[str]
    steps: list[Step]
    pass_criteria: list[str]
    on_failure: list[str]
    notes: list[str]
    build_flags: str
    artifacts: dict[str, list[str]]
    config_sha256: str | None
    variant: str | None


def resolve(test: ManualTest, variant: str | None = None) -> ResolvedTest:
    if variant is not None and variant not in test.variants:
        raise KeyError(f"{test.slug}: unknown variant {variant!r}; expected one of {sorted(test.variants)}")
    v = test.variants.get(variant) if variant is not None else None
    build_id = test.slug if variant is None else f"{test.slug}_{variant}"
    return ResolvedTest(
        slug=test.slug,
        build_id=build_id,
        title=test.title,
        priority=test.priority,
        proves=test.proves,
        seed=test.seed if (v is None or v.seed is None) else v.seed,
        options={**test.options, **(v.options if v else {})},
        start_inventory={**test.start_inventory, **(v.start_inventory if v else {})},
        plando=list(test.plando if (v is None or v.plando is None) else v.plando),
        starting_room=test.starting_room if (v is None or v.starting_room is None) else v.starting_room,
        companions=list(test.companions if (v is None or v.companions is None) else v.companions),
        setup=list(test.setup),
        steps=list(test.steps if (v is None or v.steps is None) else v.steps),
        pass_criteria=list(test.pass_criteria if (v is None or v.pass_criteria is None) else v.pass_criteria),
        on_failure=list(test.on_failure),
        notes=list(test.notes if (v is None or v.notes is None) else v.notes),
        build_flags=test.build_flags,
        artifacts={name: list(lines) for name, lines in test.artifacts.items()},
        config_sha256=(v.config_sha256 if (v and v.config_sha256) else test.config_sha256),
        variant=variant,
    )


# --------------------------------------------------------------------------
# Forced starting room (MANUAL_TEST_PLAN.md section 3.3)
# --------------------------------------------------------------------------


def _find_node_id(ap_name: str):
    from worlds.metroidprime2.logic.db_reader import load_game_database

    db = load_game_database()
    for node in db.all_nodes():
        if node.ap_name == ap_name:
            return node.id
    raise KeyError(f"no logic-database node named {ap_name!r}")


@contextlib.contextmanager
def forced_starting_room(ap_name: str):
    """For the duration of the context, every ``MetroidPrime2World.
    generate_early`` run overwrites its chosen starting room with
    ``ap_name`` (a ``NodeId.ap_name``), then rebuilds the two assignments
    derived from the origin (translator gates, dock rando).

    The override happens *after* the original ``generate_early`` -- so the
    seed's own random draws for the (discarded) vanilla/random start are
    unaffected -- and the node is asserted to be a legal ``AreaReference``
    for OPR's ``edit_starting_area_dol`` (a ``valid_starting_location``).
    """
    import worlds.metroidprime2 as mp2
    from worlds.metroidprime2.logic.db_reader import load_game_database
    from worlds.metroidprime2.logic.dock_rando import build_dock_rando_assignment
    from worlds.metroidprime2.logic.translator_gate_rando import build_translator_gate_assignment

    db = load_game_database()
    node_id = _find_node_id(ap_name)
    candidates = db.starting_location_candidates("anywhere")
    if node_id not in candidates:
        raise ValueError(
            f"{ap_name!r} is not a legal starting location "
            f"(not in the DB's {len(candidates)} valid_starting_location nodes)"
        )

    original = mp2.MetroidPrime2World.generate_early

    def patched(self) -> None:
        original(self)
        self.starting_location = node_id
        self.origin_region_name = ap_name
        self.translator_gate_assignment = build_translator_gate_assignment(self)
        self.dock_rando = build_dock_rando_assignment(self)

    mp2.MetroidPrime2World.generate_early = patched
    try:
        yield node_id
    finally:
        mp2.MetroidPrime2World.generate_early = original


# --------------------------------------------------------------------------
# Player YAMLs
# --------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


def _slot_yaml(slot: SlotSpec) -> str:
    import yaml  # type: ignore[import-untyped]  # MultiWorldGG ships no PyYAML stubs

    document: dict[str, Any] = {"name": slot.name, "game": slot.game}
    game_options: dict[str, Any] = dict(slot.options)
    if slot.start_inventory:
        game_options["start_inventory"] = dict(slot.start_inventory)
    if slot.plando:
        game_options["plando_items"] = list(slot.plando)
    document[slot.game] = game_options
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def _write_player_yamls(resolved: ResolvedTest, players_dir: Path) -> None:
    players_dir.mkdir(parents=True, exist_ok=True)
    primary = SlotSpec(
        name=resolved.slug,
        game=PRIMARY_GAME,
        options=resolved.options,
        start_inventory=resolved.start_inventory,
        plando=resolved.plando,
    )
    for index, slot in enumerate([primary, *resolved.companions], start=1):
        # Numeric prefix controls player slot assignment (Generate.main
        # iterates player files casefold-sorted).
        (players_dir / f"{index:02d}_{_safe_filename(slot.name)}.yaml").write_text(
            _slot_yaml(slot), encoding="utf-8"
        )


# --------------------------------------------------------------------------
# Generation (in-process, so forced_starting_room applies)
# --------------------------------------------------------------------------


def _run_generation(resolved: ResolvedTest, players_dir: Path, out_dir: Path):
    from Generate import main as generate_main
    from Generate import mystery_argparse
    from Main import main as main_main

    argv = [
        "--player_files_path",
        str(players_dir),
        "--outputpath",
        str(out_dir),
        "--seed",
        str(resolved.seed),
        "--spoiler",
        "3",
        "--plando",
        "items",
        "--outputname",
        resolved.build_id,
    ]
    args, seed = generate_main(mystery_argparse(argv))
    # Generate.main always overwrites outputname with the random seed name;
    # pin it back to the slug so the generated archive/AP outputs have a
    # stable, per-test name (and seed_name, used by world_uuid, is stable too).
    args.outputname = resolved.build_id
    return main_main(args, seed)


def _generated_zip(out_dir: Path, build_id: str) -> Path:
    path = out_dir / f"AP_{build_id}.zip"
    if not path.is_file():
        raise FileNotFoundError(f"generation did not produce {path}")
    return path


def _extract_first(zip_path: Path, out_dir: Path, suffix: str, target_name: str) -> Path | None:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.endswith(suffix)]
        if not members:
            return None
        target = out_dir / target_name
        with zf.open(members[0]) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def config_sha256(apmp2_path: Path) -> str:
    with zipfile.ZipFile(apmp2_path) as zf:
        data = zf.read("config.json")
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Patching
# --------------------------------------------------------------------------


def _default_iso() -> str | None:
    try:
        from settings import get_settings

        value = get_settings()["metroidprime2_options"]["rom_file"]
    except Exception:
        return None
    return str(value) if value else None


def _resolve_iso(iso: str | None, pal: bool) -> str:
    if iso:
        return iso
    if pal:
        candidate = REPO_ROOT / "echoes-pal.iso"
        if candidate.is_file():
            return str(candidate)
    default = _default_iso()
    if default and os.path.isfile(default):
        return default
    raise SystemExit(
        "No ISO given and no usable host.yaml metroidprime2_options.rom_file found; pass --iso PATH."
    )


def _cosmetics() -> dict[str, Any]:
    from settings import get_settings

    from ...settings import cosmetics_dict

    return cosmetics_dict(get_settings()["metroidprime2_options"])


def _patch(apmp2: Path, iso: str) -> str:
    from ...client.patcher_runner import patch_iso_with_ap
    from ...utils import setup_libs

    setup_libs()
    return patch_iso_with_ap(apmp2, iso, _cosmetics())


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


@dataclass
class BuildResult:
    slug: str
    variant: str | None
    build_id: str
    out_dir: Path
    zip_path: Path | None = None
    apmp2_path: Path | None = None
    spoiler_path: Path | None = None
    iso_path: Path | None = None
    actual_sha256: str | None = None
    hash_ok: bool | None = None
    repin_value: str | None = None

    def lines(self) -> list[str]:
        out = [f"Output directory: `{self.out_dir}`"]
        if self.zip_path:
            out.append(f"Host this with: `python MultiServer.py {self.zip_path}`")
        if self.apmp2_path:
            out.append(f"Client file: `{self.apmp2_path}`")
        if self.iso_path:
            out.append(f"Patched ISO: `{self.iso_path}`")
        elif self.apmp2_path:
            from ...utils import get_output_path

            out.append(f"Patched ISO: `{get_output_path(str(self.apmp2_path))}` (not built)")
        if self.actual_sha256:
            status = "pinned OK" if self.hash_ok else ("unpinned" if self.hash_ok is None else "MISMATCH")
            out.append(f"config.json sha256: `{self.actual_sha256}` ({status})")
            if self.hash_ok is not True and self.repin_value:
                out.append(f'  (--repin) config_sha256 = "{self.repin_value}"')
        return out


def build(
    test: ManualTest,
    iso: str | None = None,
    outdir: str | os.PathLike[str] | None = None,
    *,
    pal: bool = False,
    patch: bool = True,
    variant: str | None = None,
    clean: bool = False,
    repin: bool = False,
) -> BuildResult:
    resolved = resolve(test, variant)
    base = Path(outdir) if outdir is not None else DEFAULT_OUT_BASE
    # --pal tags the output directory so a PAL and an NTSC build of the same
    # test cannot clobber each other (their config.json is identical -- the
    # difference is only which DOL the ISO targets).
    out_dir = base / (f"{resolved.build_id}_pal" if pal else resolved.build_id)

    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = BuildResult(slug=resolved.slug, variant=variant, build_id=resolved.build_id, out_dir=out_dir)

    _write_player_yamls(resolved, out_dir / "players")
    for name, lines in resolved.artifacts.items():
        (out_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    context = forced_starting_room(resolved.starting_room) if resolved.starting_room else contextlib.nullcontext()
    with context:
        _run_generation(resolved, out_dir / "players", out_dir / "out")

    gen_zip = _generated_zip(out_dir / "out", resolved.build_id)
    result.zip_path = out_dir / f"{resolved.build_id}.zip"
    shutil.copyfile(gen_zip, result.zip_path)

    apmp2 = _extract_first(gen_zip, out_dir, ".apmp2", f"{resolved.build_id}.apmp2")
    if apmp2 is None:
        raise FileNotFoundError(f"no .apmp2 found inside {gen_zip}")
    result.apmp2_path = apmp2
    result.spoiler_path = _extract_first(
        gen_zip, out_dir, "Spoiler.txt", f"{resolved.build_id}_Spoiler.txt"
    )

    result.actual_sha256 = config_sha256(apmp2)
    if resolved.config_sha256 is None:
        result.hash_ok = None
        result.repin_value = result.actual_sha256
    else:
        result.hash_ok = result.actual_sha256 == resolved.config_sha256
        if not result.hash_ok:
            result.repin_value = result.actual_sha256
            message = (
                f"{resolved.build_id}: config.json hash mismatch\n"
                f"  expected: {resolved.config_sha256}\n"
                f"  actual:   {result.actual_sha256}\n"
                "The seed's generated patch data changed (option default, DB, or "
                "patch_data.py change). If that is expected, re-run with --repin and "
                "paste the value above into the test module."
            )
            if not repin:
                raise AssertionError(message)
            print(message)

    if patch:
        iso_path = _resolve_iso(iso, pal)
        from ...client.patcher_runner import detect_iso_version

        detected = detect_iso_version(iso_path)
        if pal and detected != "PAL":
            raise SystemExit(f"--pal was given but {iso_path} is {detected}")
        result.iso_path = Path(_patch(apmp2, iso_path))

    return result


# --------------------------------------------------------------------------
# README / INSTRUCTIONS rendering
# --------------------------------------------------------------------------


def render_instructions(
    test: ManualTest,
    *,
    variant: str | None = None,
    base_dir: str = "manual_tests",
    paths: BuildResult | None = None,
) -> str:
    resolved = resolve(test, variant)
    build_dir = Path(base_dir) / resolved.build_id
    apmp2 = str(paths.apmp2_path) if paths and paths.apmp2_path else f"{build_dir}/{resolved.build_id}.apmp2"
    zip_path = str(paths.zip_path) if paths and paths.zip_path else f"{build_dir}/{resolved.build_id}.zip"
    variant_flag = f" --variant {resolved.variant}" if resolved.variant else ""
    flags = f"{variant_flag}{(' ' + resolved.build_flags) if resolved.build_flags else ''}"
    heading = resolved.slug.upper()

    lines: list[str] = []
    lines.append(f"### {heading} -- `{resolved.build_id}` ({resolved.priority})")
    lines.append("")
    lines.append(f"*Proves: {resolved.proves}*")
    lines.append("")

    if resolved.setup:
        lines.append("Prerequisites for this test:")
        lines.extend(f"* {item}" for item in resolved.setup)
        lines.append("")

    lines.append("Build:")
    lines.append("```")
    lines.append(
        f"python -m worlds.metroidprime2.test.manual.{resolved.slug} --iso <vanilla.iso>{flags}"
    )
    lines.append("```")
    lines.append("")

    lines.append("What the build contains:")
    lines.append(
        f"* starting room: `{resolved.starting_room or 'vanilla (Temple Grounds/Landing Site/Save Station)'}`"
    )
    if resolved.options:
        rendered = ", ".join(f"`{k}={v}`" for k, v in sorted(resolved.options.items()))
        lines.append(f"* options: {rendered}")
    else:
        lines.append("* options: world defaults")
    if resolved.start_inventory:
        items = ", ".join(f"`{name}` x{count}" for name, count in sorted(resolved.start_inventory.items()))
        lines.append(f"* start inventory: {items}")
    if resolved.plando:
        lines.append(f"* plando: {len(resolved.plando)} placement(s):")
        for entry in resolved.plando:
            item = entry.get("item") or entry.get("items")
            location = entry.get("location") or entry.get("locations") or "Everywhere"
            lines.append(f"  * `{item}` -> `{location}`")
    if resolved.companions:
        names = ", ".join(f"{c.name} ({c.game})" for c in resolved.companions)
        lines.append(f"* companion slots: {names}")
    lines.append("")

    if resolved.notes:
        lines.append("Notes / derived values:")
        lines.extend(f"* {note}" for note in resolved.notes)
        lines.append("")

    for art_name, art_lines in resolved.artifacts.items():
        lines.append(f"Sidecar `{art_name}` (written into the build output dir, {len(art_lines)} lines):")
        lines.append("```")
        lines.extend(art_lines)
        lines.append("```")
        lines.append("")

    lines.append("Run:")
    lines.append("```")
    lines.append(
        f"1. Build      python -m worlds.metroidprime2.test.manual.{resolved.slug}"
        f" --iso <vanilla.iso>{flags}"
    )
    lines.append(f"2. Host       python MultiServer.py {zip_path}")
    lines.append(f'3. Connect    python Launcher.py "Metroid Prime 2 Client" {apmp2} <vanilla.iso>')
    lines.append("               (the client reuses the already-patched ISO instead of re-patching)")
    lines.append("```")
    lines.append("")

    if resolved.steps:
        lines.append("Steps:")
        for index, step in enumerate(resolved.steps, start=1):
            lines.append(f"{index}. **Do:** {step.do}")
            lines.append(f"   **Expect:** {step.expect}")
            if step.why:
                lines.append(f"   *(exercises: {step.why})*")
        lines.append("")

    if resolved.pass_criteria:
        lines.append("Pass if:")
        lines.extend(f"* {item}" for item in resolved.pass_criteria)
        lines.append("")

    if resolved.on_failure:
        lines.append("If it fails, look at:")
        lines.extend(f"* {item}" for item in resolved.on_failure)
        lines.append("")

    if paths is not None:
        lines.append("Build info:")
        lines.extend(f"* {line}" for line in paths.lines())
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cli(test: ManualTest) -> None:
    parser = argparse.ArgumentParser(
        prog=f"python -m worlds.metroidprime2.test.manual.{test.slug}",
        description=f"{test.title} ({test.priority}): proves {test.proves}",
    )
    parser.add_argument("--iso", default=None, help="Vanilla NTSC-U (or PAL with --pal) ISO path.")
    parser.add_argument("--pal", action="store_true", help="Use the PAL ISO and tag the output dir.")
    parser.add_argument("--out", default=None, help="Base output directory (default: manual_tests/).")
    parser.add_argument("--clean", action="store_true", help="Wipe the test's output directory first.")
    parser.add_argument("--no-patch", action="store_true", help="Generate/verify only; do not patch an ISO.")
    parser.add_argument("--verify", action="store_true", help="Build, check the pinned hash, do not patch.")
    parser.add_argument(
        "--repin", action="store_true", help="On a hash mismatch, print the new pin instead of failing."
    )
    parser.add_argument("--print-readme", action="store_true", help="Print this test's README section and exit.")
    parser.add_argument("--variant", default=None, help="Build a declared variant (see MANUAL_TEST_PLAN.md).")
    args = parser.parse_args()

    if args.print_readme:
        print(render_instructions(test, variant=args.variant))
        return

    result = build(
        test,
        iso=args.iso,
        outdir=args.out,
        pal=args.pal,
        patch=not (args.no_patch or args.verify),
        variant=args.variant,
        clean=args.clean,
        repin=args.repin,
    )

    instructions = render_instructions(test, variant=args.variant, paths=result)
    print(instructions)
    (result.out_dir / "INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")


__all__ = [
    "BuildResult",
    "ManualTest",
    "ResolvedTest",
    "SlotSpec",
    "Step",
    "Variant",
    "build",
    "cli",
    "config_sha256",
    "forced_starting_room",
    "render_instructions",
    "resolve",
]
