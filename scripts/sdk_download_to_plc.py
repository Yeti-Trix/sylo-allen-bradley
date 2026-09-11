#!/usr/bin/env python3
"""Download (push) a working .acd project to a Logix controller.

Rockwell terminology: download = copy project from PC to PLC.

GATED by the operator-managed download allowlist
(packages/sylo-logicforge/assets/download-allowlist.json). The agent cannot
download to any IP not present and enabled in that list — there is no override.
The agent also never edits the allowlist; only the operator does, via the
LogicForge Settings tab.

Flow:
  1. Load allowlist → refuse if downloads disabled or IP not allowlisted.
  2. Read controller keyswitch via ciplogix (lightweight CIP read).
  3. Open the working .acd, set the communications path.
  4. Ensure controller is in Program mode (auto-switch if key is in REM;
     refuse if key is hard RUN — can't get to Program remotely).
  5. SDK download().
  6. Leave controller in the configured post_download_mode (Program or Run)
     when the key is in REM. Hard-key positions keep their fixed mode.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from _download_allowlist import check_ip_allowed, load_allowlist, save_allowlist  # noqa: F401
from _json_out import emit, emit_error
from _run_yaml import find_working_acd, read_run_yaml, write_run_yaml
from _sdk_import import sdk_logs_to_stderr
from _sdk_paths import ensure_logix_designer_sdk, require_windows
from _sdk_plc import normalize_comm_path


def _ensure_ciplogix() -> None:
    try:
        import ciplogix  # noqa: F401

        return
    except ImportError:
        pass

    import subprocess

    root = Path(__file__).resolve().parent.parent
    wheels = list((root / "vendor" / "ciplogix").glob("ciplogix-*.whl"))
    if not wheels:  # vendored ciplogix wheel moved to sylo-plc-comms (2026-09-09 split)
        try:
            comms_vendor = root.parents[0] / "sylo-plc-comms" / "vendor" / "ciplogix"
            wheels = list(comms_vendor.glob("ciplogix-*.whl"))
        except (OSError, RuntimeError):
            pass
    if not wheels:
        raise RuntimeError("ciplogix wheel not found under vendor/ciplogix/.")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", str(wheels[0]), "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _read_keyswitch(ip: str) -> dict:
    from ciplogix import LogixDriver

    plc = LogixDriver(ip, init_tags=False)
    try:
        plc.open()
    except Exception as exc:
        return {"reachable": False, "error": str(exc), "keyswitch": None}

    if not plc.connected:
        return {"reachable": False, "error": "connection did not open", "keyswitch": None}

    try:
        info = plc.get_plc_info()
    except Exception as exc:
        plc.close()
        return {"reachable": True, "error": str(exc), "keyswitch": None}

    keyswitch = str(info.get("keyswitch", "UNKNOWN") or "UNKNOWN").upper()
    plc.close()
    return {"reachable": True, "error": None, "keyswitch": keyswitch}


async def _download_to_plc(
    acd_path: Path,
    comm_path: str,
    need_mode_switch: bool,
    post_download_mode: str,
    key_is_rem: bool,
) -> dict:
    from logix_designer_sdk import (
        LogixProject,
        RequestedControllerMode,
        StdOutEventLogger,
    )

    with sdk_logs_to_stderr():
        project = await LogixProject.open_logix_project(str(acd_path), StdOutEventLogger())
        await project.set_communications_path(comm_path)

        switched_to_program = False
        if need_mode_switch:
            # Key is REM and controller isn't in Program — switch it.
            await project.go_online()
            try:
                await project.change_controller_mode(RequestedControllerMode.PROGRAM)
                switched_to_program = True
            finally:
                await project.go_offline()

        # download() requires offline connection state.
        await project.download()

        returned_to_run = False
        if post_download_mode == "run" and key_is_rem:
            await project.go_online()
            try:
                await project.change_controller_mode(RequestedControllerMode.RUN)
                returned_to_run = True
            finally:
                await project.go_offline()

        await project.close()

    return {
        "switched_to_program": switched_to_program,
        "returned_to_run": returned_to_run,
    }


def resolve_acd(args: argparse.Namespace) -> tuple[Path, Path | None]:
    run_dir: Path | None = None
    if args.run_dir.strip():
        run_dir = Path(args.run_dir).expanduser().resolve()

    acd_path: Path | None = None
    if args.acd.strip():
        acd_path = Path(args.acd).expanduser().resolve()
    elif run_dir:
        acd_path = find_working_acd(run_dir)
        if acd_path is None:
            run_data = read_run_yaml(run_dir)
            base = run_data.get("base_acd")
            if isinstance(base, str) and base.strip():
                acd_path = Path(base).expanduser().resolve()

    if acd_path is None or not acd_path.is_file():
        emit_error("ACD not found — pass --acd or --run-dir with a working/*.acd copy")

    return acd_path, run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="SDK download: working .acd → PLC (allowlist-gated)")
    parser.add_argument("--ip", default="", help="Controller IPv4 address (must be in allowlist)")
    parser.add_argument(
        "--comm-path",
        default="",
        help="Full Rockwell communications path (overrides --ip)",
    )
    parser.add_argument("--acd", default="", help="Working .acd to push")
    parser.add_argument("--run-dir", default="", help="Run folder; uses working/*.dev.acd")
    args = parser.parse_args()

    require_windows()

    comm_raw = args.comm_path.strip() or args.ip.strip()
    if not comm_raw:
        emit_error("Pass --ip or --comm-path for the target controller")

    try:
        comm_path = normalize_comm_path(comm_raw)
    except ValueError as exc:
        emit_error(str(exc))

    # --- Gate 1: allowlist ---
    allowed, reason = check_ip_allowed(comm_raw)
    if not allowed:
        allowlist = load_allowlist()
        emit_error(
            reason,
            comm_path=comm_path,
            allow_downloads=allowlist.get("allow_downloads", False),
            allowed_ips=[e.get("ip") for e in allowlist.get("ips", []) if isinstance(e, dict)],
        )

    allowlist = load_allowlist()
    post_download_mode = allowlist.get("post_download_mode", "program")
    if post_download_mode not in ("program", "run"):
        post_download_mode = "program"

    # --- Gate 2: resolve ACD ---
    try:
        wheel = ensure_logix_designer_sdk()
    except RuntimeError as exc:
        emit_error(str(exc))

    acd_path, run_dir = resolve_acd(args)

    # --- Gate 3: read keyswitch (ciplogix) ---
    bare_ip = args.ip.strip() or comm_raw
    try:
        _ensure_ciplogix()
    except Exception as exc:
        emit_error(f"ciplogix setup failed: {exc}")

    try:
        status = _read_keyswitch(bare_ip)
    except Exception as exc:
        emit_error(f"PLC status read failed: {exc}")

    if not status.get("reachable"):
        emit_error(
            f"Controller {bare_ip} not reachable: {status.get('error')}",
            comm_path=comm_path,
        )

    keyswitch = status.get("keyswitch") or "UNKNOWN"
    key_is_rem = keyswitch.startswith("REMOTE")
    in_program = "PROG" in keyswitch

    # Hard RUN key → cannot get to Program remotely → download will fail.
    if keyswitch == "RUN":
        emit_error(
            f"Controller key switch is in hard RUN ({keyswitch}). "
            "Move the key to REM or PROG before downloading.",
            comm_path=comm_path,
            keyswitch=keyswitch,
        )

    need_mode_switch = key_is_rem and not in_program

    # --- Download ---
    try:
        result = asyncio.run(
            _download_to_plc(acd_path, comm_path, need_mode_switch, post_download_mode, key_is_rem)
        )
    except Exception as exc:
        emit_error(
            f"SDK download to PLC failed: {exc}",
            comm_path=comm_path,
            acd_path=str(acd_path),
            keyswitch=keyswitch,
        )

    if run_dir:
        write_run_yaml(
            run_dir,
            {
                "status": "downloaded_to_plc",
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "plc_comm_path": comm_path,
                "plc_ip": bare_ip,
                "keyswitch": keyswitch,
                "post_download_mode": post_download_mode,
                "switched_to_program": result.get("switched_to_program", False),
                "returned_to_run": result.get("returned_to_run", False),
            },
        )

    final_mode = (
        "RUN" if result.get("returned_to_run") else
        ("PROGRAM" if (key_is_rem or keyswitch == "PROG") else keyswitch)
    )

    emit(
        {
            "ok": True,
            "comm_path": comm_path,
            "plc_ip": bare_ip,
            "acd_path": str(acd_path),
            "sdk_wheel": wheel,
            "run_dir": str(run_dir) if run_dir else None,
            "keyswitch_before": keyswitch,
            "switched_to_program": result.get("switched_to_program", False),
            "returned_to_run": result.get("returned_to_run", False),
            "final_mode": final_mode,
            "operator_chat": (
                f"Downloaded {acd_path.name} → controller {bare_ip} "
                f"(keyswitch was {keyswitch}). "
                f"Controller left in {final_mode} mode."
            ),
        }
    )


if __name__ == "__main__":
    main()