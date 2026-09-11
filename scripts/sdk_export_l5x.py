#!/usr/bin/env python3
"""Export .ACD to .L5X via Logix Designer SDK save_as (Phase 1.0)."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from _json_out import emit, emit_error
from _run_yaml import find_working_acd, read_run_yaml, write_run_yaml
from _sdk_import import sdk_logs_to_stderr
from _sdk_paths import ensure_logix_designer_sdk, require_windows


async def export_acd(acd_path: Path, l5x_path: Path, detailed_l5x: bool) -> None:
    from logix_designer_sdk import LogixProject, StdOutEventLogger

    l5x_path.parent.mkdir(parents=True, exist_ok=True)
    with sdk_logs_to_stderr():
        project = await LogixProject.open_logix_project(str(acd_path), StdOutEventLogger())
        await project.save_as(str(l5x_path), True, detailed_l5x)


def resolve_acd_and_output(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    run_dir: Path | None = None
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()

    acd_path: Path | None = None
    if args.acd:
        acd_path = Path(args.acd).expanduser().resolve()
    elif run_dir:
        acd_path = find_working_acd(run_dir)
        if acd_path is None:
            run_data = read_run_yaml(run_dir)
            base = run_data.get("base_acd")
            if isinstance(base, str) and base.strip():
                acd_path = Path(base).expanduser().resolve()

    if acd_path is None or not acd_path.is_file():
        emit_error("ACD not found — pass --acd or --run-dir with a working/*.acd copy or run.yaml base_acd")

    l5x_path: Path
    if args.output:
        l5x_path = Path(args.output).expanduser().resolve()
    elif run_dir:
        l5x_path = run_dir / "exports" / "iter-0" / "controller.l5x"
    else:
        l5x_path = acd_path.with_suffix(".l5x")

    return acd_path, l5x_path, run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="SDK save_as: ACD → L5X for LogicForge parse")
    parser.add_argument("--acd", default="", help="Path to .acd (or use --run-dir)")
    parser.add_argument("--output", default="", help="Output .l5x path")
    parser.add_argument("--run-dir", default="", help="Run folder; default output exports/iter-0/controller.l5x")
    parser.add_argument(
        "--detailed-l5x",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="SDK detailed_l5x flag (default true — required for parse)",
    )
    args = parser.parse_args()

    require_windows()

    try:
        wheel = ensure_logix_designer_sdk()
    except RuntimeError as exc:
        emit_error(str(exc))

    acd_path, l5x_path, run_dir = resolve_acd_and_output(args)

    try:
        asyncio.run(export_acd(acd_path, l5x_path, args.detailed_l5x))
    except Exception as exc:  # SDK raises many typed errors
        emit_error(f"SDK export failed: {exc}", acd_path=str(acd_path), output_path=str(l5x_path))

    if run_dir:
        write_run_yaml(
            run_dir,
            {
                "status": "acd_exported",
                "exported_l5x": str(l5x_path),
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    emit(
        {
            "ok": True,
            "acd_path": str(acd_path),
            "l5x_path": str(l5x_path),
            "detailed_l5x": args.detailed_l5x,
            "sdk_wheel": wheel,
            "run_dir": str(run_dir) if run_dir else None,
            "operator_chat": (
                f"Exported {acd_path.name} → {l5x_path}. "
                "Next: logicforge_parse_l5x on this L5X, schematic pull, then match/descriptions."
            ),
        }
    )


if __name__ == "__main__":
    main()
