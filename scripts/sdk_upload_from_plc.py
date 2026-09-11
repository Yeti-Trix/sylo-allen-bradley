#!/usr/bin/env python3
"""Upload (pull) a project from a Logix controller into a new .acd file.

Rockwell terminology: upload = copy project from PLC to PC.
This script never calls SDK download (PC → PLC).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from _json_out import emit, emit_error
from _run_yaml import write_run_yaml
from _sdk_paths import ensure_logix_designer_sdk, require_windows
from _sdk_plc import acd_name_for_comm_path, normalize_comm_path, upload_from_plc_to_acd


def write_yaml_or_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore

        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except ImportError:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_output(args: argparse.Namespace, comm_path: str) -> tuple[Path, Path | None]:
    run_dir: Path | None = None
    if args.run_dir.strip():
        run_dir = Path(args.run_dir).expanduser().resolve()
    elif args.project_dir.strip():
        project_dir = Path(args.project_dir).expanduser().resolve()
        run_id = args.run_id.strip() or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
        run_dir = project_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "working").mkdir(parents=True, exist_ok=True)
        (run_dir / "exports" / "iter-0").mkdir(parents=True, exist_ok=True)
        (run_dir / "parse").mkdir(parents=True, exist_ok=True)

    if args.output.strip():
        acd_path = Path(args.output).expanduser().resolve()
        if run_dir is None:
            acd_path.parent.mkdir(parents=True, exist_ok=True)
        return acd_path, run_dir

    if run_dir is None:
        emit_error("Pass --output or --run-dir (or --project-dir to create a run folder)")

    stem = acd_name_for_comm_path(comm_path)
    acd_path = run_dir / "working" / f"{stem}.acd"
    return acd_path, run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="SDK upload: PLC to new .acd (read-only toward PLC)")
    parser.add_argument("--ip", default="", help="Controller IPv4 address")
    parser.add_argument(
        "--comm-path",
        default="",
        help="Full Rockwell communications path (overrides --ip), e.g. AB_ETHIP-1\\10.0.0.1\\Backplane\\0",
    )
    parser.add_argument("--output", default="", help="Output .acd path")
    parser.add_argument("--run-dir", default="", help="Existing run folder; saves working/<name>.acd")
    parser.add_argument("--project-dir", default="", help="Create runs/<run-id>/ under this project")
    parser.add_argument("--run-id", default="", help="Run id when using --project-dir")
    args = parser.parse_args()

    require_windows()
    try:
        wheel = ensure_logix_designer_sdk()
    except RuntimeError as exc:
        emit_error(str(exc))

    comm_raw = args.comm_path.strip() or args.ip.strip()
    if not comm_raw:
        emit_error("Pass --ip or --comm-path for the target controller")

    try:
        comm_path = normalize_comm_path(comm_raw)
    except ValueError as exc:
        emit_error(str(exc))

    acd_path, run_dir = resolve_output(args, comm_path)

    try:
        asyncio.run(upload_from_plc_to_acd(acd_path, comm_path))
    except Exception as exc:
        emit_error(
            f"SDK upload from PLC failed: {exc}",
            comm_path=comm_path,
            output_path=str(acd_path),
        )

    if run_dir:
        run_id = run_dir.name
        write_run_yaml(
            run_dir,
            {
                "run_id": run_id,
                "type": "plc-upload",
                "status": "uploaded_from_plc",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "plc_comm_path": comm_path,
                "working_acd": str(acd_path),
                "base_acd": str(acd_path),
            },
        )
        project_dir = run_dir.parent.parent
        project_yaml = project_dir / "project.yaml"
        if not project_yaml.is_file():
            write_yaml_or_json(
                project_yaml,
                {
                    "project_id": project_dir.name,
                    "base_acd": str(acd_path),
                    "source": "plc_upload",
                },
            )

    emit(
        {
            "ok": True,
            "comm_path": comm_path,
            "acd_path": str(acd_path),
            "sdk_wheel": wheel,
            "run_dir": str(run_dir) if run_dir else None,
            "operator_chat": (
                f"Uploaded project from controller ({comm_path}) → {acd_path.name}. "
                "Next: allen_bradley_sdk_export_l5x on this path or run_dir, then "
                "logicforge_parse_l5x / logicforge_l5x_explore to inspect logic. "
                "This tool cannot download to the PLC."
            ),
        }
    )


if __name__ == "__main__":
    main()
