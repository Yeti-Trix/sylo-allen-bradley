#!/usr/bin/env python3
"""SDK partial import: merge an L5X fragment into the run's working .acd copy."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from _json_out import emit, emit_error
from _run_yaml import find_working_acd, write_run_yaml
from _sdk_import import partial_import_from_l5x
from _sdk_paths import ensure_logix_designer_sdk, require_windows


def resolve_acd(args: argparse.Namespace) -> tuple[Path, Path | None]:
    run_dir: Path | None = None
    if args.run_dir.strip():
        run_dir = Path(args.run_dir).expanduser().resolve()
    acd_path: Path | None = None
    if args.acd.strip():
        acd_path = Path(args.acd).expanduser().resolve()
    elif run_dir:
        acd_path = find_working_acd(run_dir)
    if acd_path is None or not acd_path.is_file():
        emit_error("ACD not found — pass --acd or --run-dir with a working/*.acd copy")
    return acd_path, run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="SDK partial import L5X fragment into .acd")
    parser.add_argument("--acd", default="", help="Target .acd path")
    parser.add_argument("--run-dir", default="", help="Run folder (uses working/project.acd)")
    parser.add_argument("--l5x", required=True, help="L5X fragment to import")
    parser.add_argument(
        "--xpath",
        default="Controller/Tags",
        help="Partial import XPath (default Controller/Tags)",
    )
    args = parser.parse_args()

    require_windows()
    try:
        wheel = ensure_logix_designer_sdk()
    except RuntimeError as exc:
        emit_error(str(exc))

    acd_path, run_dir = resolve_acd(args)
    fragment = Path(args.l5x).expanduser().resolve()
    if not fragment.is_file():
        emit_error(f"L5X fragment not found: {fragment}")

    try:
        asyncio.run(partial_import_from_l5x(acd_path, args.xpath.strip(), fragment))
    except Exception as exc:
        emit_error(
            f"SDK partial import failed: {exc}",
            acd_path=str(acd_path),
            l5x_path=str(fragment),
            xpath=args.xpath,
        )

    if run_dir:
        write_run_yaml(
            run_dir,
            {
                "last_import_l5x": str(fragment),
                "last_import_xpath": args.xpath,
            },
        )

    emit(
        {
            "ok": True,
            "acd_path": str(acd_path),
            "l5x_path": str(fragment),
            "xpath": args.xpath,
            "sdk_wheel": wheel,
            "run_dir": str(run_dir) if run_dir else None,
            "operator_chat": (
                f"Imported {fragment.name} into {acd_path.name} at {args.xpath}. "
                "Re-export with allen_bradley_sdk_export_l5x to verify parse."
            ),
        }
    )


if __name__ == "__main__":
    main()
