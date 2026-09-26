"""Rebuilds every manual test -- and every declared variant -- in one pass.

Generates each build and checks its pinned ``config_sha256`` the same way
``harness.cli`` does for a single test; ISO patching is opt-in since most
rebuilds only care whether generation/patch data drifted, not about
producing a playable ISO for all 16 builds at once.

Run under MultiWorldGG's interpreter, same as any other manual test::

    cd MultiWorldGG
    SKIP_REQUIREMENTS_UPDATE=1 .venv/bin/python \\
        -m worlds.metroidprime2.test.manual.rebuild_all [--patch --iso PATH] [--repin]

Without ``--patch``, this only generates and verifies (mirrors running every
test with ``--verify`` individually). With ``--repin``, a hash mismatch
prints the new pin instead of failing that test's build -- paste the printed
values into the source files by hand, then re-run ``build_readme.py`` if any
option/plando text changed.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from .catalog import load_tests
from .harness import BuildResult, build


@dataclass
class Outcome:
    label: str
    result: BuildResult | None
    error: Exception | None = None


def _labels(name: str, variant: str | None) -> str:
    return name if variant is None else f"{name} --variant {variant}"


def rebuild_all(
    *,
    iso: str | None,
    outdir: str | None,
    pal: bool,
    patch: bool,
    repin: bool,
    clean: bool,
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for name, test in load_tests():
        for variant in [None, *sorted(test.variants)]:
            label = _labels(name, variant)
            print(f"==> {label}", file=sys.stderr)
            try:
                result = build(
                    test,
                    iso=iso,
                    outdir=outdir,
                    pal=pal,
                    patch=patch,
                    variant=variant,
                    clean=clean,
                    repin=repin,
                )
            except Exception as exc:  # noqa: BLE001 -- reported in the summary, not swallowed
                outcomes.append(Outcome(label, None, exc))
                print(f"    FAILED: {exc}", file=sys.stderr)
                continue
            status = "pinned OK" if result.hash_ok else ("unpinned" if result.hash_ok is None else "MISMATCH")
            print(f"    {status}: {result.actual_sha256}", file=sys.stderr)
            outcomes.append(Outcome(label, result))
    return outcomes


def _print_summary(outcomes: list[Outcome]) -> bool:
    """Prints a pass/fail/mismatch/unpinned breakdown; returns True if the run is clean."""
    failed = [o for o in outcomes if o.error is not None]
    mismatched = [o for o in outcomes if o.result is not None and o.result.hash_ok is False]
    unpinned = [o for o in outcomes if o.result is not None and o.result.hash_ok is None]

    print(f"\n{len(outcomes) - len(failed)}/{len(outcomes)} builds completed.")

    if unpinned:
        print(f"\n{len(unpinned)} unpinned (no config_sha256 set):")
        for o in unpinned:
            print(f"  {o.label}: config_sha256 = \"{o.result.actual_sha256}\"")

    if mismatched:
        print(f"\n{len(mismatched)} hash MISMATCH -- paste these into the source (config_sha256=...):")
        for o in mismatched:
            print(f"  {o.label}: config_sha256 = \"{o.result.repin_value}\"")

    if failed:
        print(f"\n{len(failed)} FAILED to build:")
        for o in failed:
            print(f"  {o.label}: {o.error}")

    return not failed and not mismatched


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m worlds.metroidprime2.test.manual.rebuild_all",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "--patch", action="store_true", help="Also patch an ISO for every build (slow; needs --iso or host.yaml)."
    )
    parser.add_argument("--iso", default=None, help="Vanilla NTSC-U (or PAL with --pal) ISO path; only used with --patch.")
    parser.add_argument("--pal", action="store_true", help="Use the PAL ISO and tag output dirs.")
    parser.add_argument("--out", default=None, help="Base output directory (default: manual_tests/).")
    parser.add_argument("--clean", action="store_true", help="Wipe each test's output directory first.")
    parser.add_argument(
        "--repin", action="store_true", help="On a hash mismatch, print the new pin instead of failing that build."
    )
    args = parser.parse_args()

    outcomes = rebuild_all(
        iso=args.iso,
        outdir=args.out,
        pal=args.pal,
        patch=args.patch,
        repin=args.repin,
        clean=args.clean,
    )
    clean = _print_summary(outcomes)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
