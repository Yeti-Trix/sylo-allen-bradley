#!/usr/bin/env python3
"""sylo-allen-bradley MCP server — Studio 5000 Logix Designer SDK wrapper.

Harness-neutral replacement for the old pi TS extension: every tool is a thin
1:1 wrapper around the standalone Python scripts in ``scripts/`` (same CLI
args, same JSON-out contract, same allowlist enforcement). Any MCP client
(Claude Code, Codex, pi via pi-mcp-adapter, ...) gets identical behavior.

Controller upload/download and .acd ↔ L5X export/import via the Rockwell
Logix Designer SDK. The SDK itself is NOT bundled — it ships with the licensed
Studio 5000 v36+ install (wheel via LOGIX_DESIGNER_SDK_WHEEL /
LOGIX_DESIGNER_SDK_SITE / vendor drop-spot). SDK scripts run on the SDK
Python 3.12 (``SYLO_SDK_PYTHON`` env or ``py -3.12`` on Windows); the
``download`` tool is hard-gated by the operator-managed download allowlist —
enforced in Python, never agent-editable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PACKAGE_ROOT / "scripts"

# Per-script timeouts in seconds (mirrors the old TS extension).
TIMEOUTS: dict[str, float] = {
    "sdk_upload_from_plc.py": 600.0,
    "sdk_download_to_plc.py": 600.0,
    "sdk_export_l5x.py": 300.0,
    "sdk_import_l5x.py": 300.0,
}
DEFAULT_TIMEOUT = 120.0

# All tools here are SDK-backed — run them on the SDK Python (3.12) so
# logix_designer_sdk imports resolve.
SDK_SCRIPTS = {
    "sdk_export_l5x.py",
    "sdk_import_l5x.py",
    "sdk_upload_from_plc.py",
    "sdk_download_to_plc.py",
}

mcp = FastMCP("allen-bradley")


# Windows env floor: some MCP harnesses launch servers with a sanitized
# environment (missing SYSTEMROOT etc.), which makes child Python processes
# hang on imports (ssl/socket). Rebuild any missing critical vars.
_WIN_ENV_FLOOR = {
    "SYSTEMROOT": r"C:\Windows",
    "SYSTEMDRIVE": "C:",
    "COMSPEC": r"C:\Windows\system32\cmd.exe",
    "PATHEXT": ".COM;.EXE;.BAT;.CMD",
}


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if os.name == "nt":
        for key, default in _WIN_ENV_FLOOR.items():
            env.setdefault(key, default)
    return env


class ToolError(Exception):
    """Raised when a wrapped script fails; surfaces as an MCP error result."""


def _script_command(script: str) -> list[str]:
    """Interpreter resolution mirroring the old TS extension exactly:
    SDK scripts -> SYLO_SDK_PYTHON, else `py -3.12` on Windows; other scripts
    -> SYLO_PYTHON, else the interpreter running this server."""
    if script in SDK_SCRIPTS:
        sdk_python = os.environ.get("SYLO_SDK_PYTHON", "").strip()
        if sdk_python:
            return [sdk_python]
        if os.name == "nt":
            return ["py", "-3.12"]
    env_python = os.environ.get("SYLO_PYTHON", "").strip()
    if env_python:
        return [env_python]
    return [sys.executable]


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().split("\n")[-lines:]).strip()


def _parse_trailing_json(stdout: str) -> dict | None:
    """Scripts emit JSON as the last thing on stdout, but the Logix Designer
    SDK's StdOutEventLogger can print INFO lines before it — parse the
    trailing JSON object instead of assuming the whole stream is JSON."""
    trimmed = stdout.strip()
    if not trimmed:
        return None
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass
    idx = trimmed.rfind("\n{")
    while idx >= 0:
        candidate = trimmed[idx + 1:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            idx = trimmed.rfind("\n{", 0, idx)
    return None


def _run_script(script: str, args: list[str]) -> str:
    timeout = TIMEOUTS.get(script, DEFAULT_TIMEOUT)
    cmd = [*_script_command(script), str(SCRIPTS_DIR / script), *args]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PACKAGE_ROOT),
            # stdin=DEVNULL is load-bearing on Windows: inheriting the MCP
            # stdio pipe makes the child's Py_Initialize lseek on that pipe
            # block forever.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=_child_env(),
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"{script} timed out after {int(timeout)}s")
    except OSError as exc:
        raise ToolError(f"failed to launch {script}: {exc}")

    parsed = _parse_trailing_json(proc.stdout)
    if parsed is None:
        detail = _tail(proc.stdout) or proc.stderr.strip() or f"{script} produced no output"
        raise ToolError(detail)
    if parsed.get("ok") is False:
        raise ToolError(str(parsed.get("error") or f"{script} failed"))
    operator_chat = parsed.get("operator_chat")
    if isinstance(operator_chat, str) and operator_chat.strip():
        return operator_chat.strip()
    return json.dumps(parsed, indent=2)


@mcp.tool()
def allen_bradley_sdk_upload_from_plc(
    ip: str | None = None,
    comm_path: str | None = None,
    output_path: str | None = None,
    run_dir: str | None = None,
    project_dir: str | None = None,
    run_id: str | None = None,
) -> str:
    """Windows + Logix Designer SDK: pull the controller project into a new offline `.acd` (Rockwell "upload"). Pass controller `ip` or full `comm_path`. Saves to `output_path` and/or creates a run folder. Read-only toward the PLC — there is no upload-to-PLC risk; downloads are separate. Follow with allen_bradley_sdk_export_l5x to read logic."""
    i = (ip or "").strip()
    cp = (comm_path or "").strip()
    if not i and not cp:
        raise ToolError("allen_bradley_sdk_upload_from_plc requires ip and/or comm_path.")
    args: list[str] = []
    if i:
        args += ["--ip", i]
    if cp:
        args += ["--comm-path", cp]
    out = (output_path or "").strip()
    rd = (run_dir or "").strip()
    pd = (project_dir or "").strip()
    rid = (run_id or "").strip()
    if out:
        args += ["--output", out]
    if rd:
        args += ["--run-dir", rd]
    if pd:
        args += ["--project-dir", pd]
    if rid:
        args += ["--run-id", rid]
    if not out and not rd and not pd:
        raise ToolError(
            "allen_bradley_sdk_upload_from_plc requires output_path, run_dir, and/or project_dir for the saved .acd."
        )
    return _run_script("sdk_upload_from_plc.py", args)


@mcp.tool()
def allen_bradley_sdk_download_to_plc(
    ip: str | None = None,
    comm_path: str | None = None,
    acd_path: str | None = None,
    run_dir: str | None = None,
) -> str:
    """Windows + Logix Designer SDK: push the working .acd project to a controller (Rockwell "download"). GATED by the operator-managed download allowlist — the agent cannot download to any IP not present and enabled there, even with operator permission, and cannot edit the allowlist. Auto-switches the controller to Program mode first if the key is in REM; refuses if the key is in hard RUN. Leaves the controller in the configured post_download_mode (Program or Run) when the key is in REM."""
    i = (ip or "").strip()
    cp = (comm_path or "").strip()
    if not i and not cp:
        raise ToolError("allen_bradley_sdk_download_to_plc requires ip and/or comm_path.")
    args: list[str] = []
    if i:
        args += ["--ip", i]
    if cp:
        args += ["--comm-path", cp]
    acd = (acd_path or "").strip()
    rd = (run_dir or "").strip()
    if acd:
        args += ["--acd", acd]
    if rd:
        args += ["--run-dir", rd]
    if not acd and not rd:
        raise ToolError("allen_bradley_sdk_download_to_plc requires acd_path and/or run_dir.")
    return _run_script("sdk_download_to_plc.py", args)


@mcp.tool()
def allen_bradley_sdk_export_l5x(
    acd_path: str | None = None,
    output_path: str | None = None,
    run_dir: str | None = None,
    detailed_l5x: bool | None = None,
) -> str:
    """Windows + Logix Designer SDK: export `.acd` → `.L5X` (save_as, detailed_l5x) so the agent can read and edit project logic as XML. Pass run_dir or acd + output paths. Set LOGIX_DESIGNER_SDK_WHEEL if import fails. Parse the export with logicforge_parse_l5x (sylo-logicforge)."""
    args: list[str] = []
    acd = (acd_path or "").strip()
    out = (output_path or "").strip()
    rd = (run_dir or "").strip()
    if acd:
        args += ["--acd", acd]
    if out:
        args += ["--output", out]
    if rd:
        args += ["--run-dir", rd]
    if detailed_l5x is False:
        args.append("--no-detailed-l5x")
    if not acd and not rd:
        raise ToolError("allen_bradley_sdk_export_l5x requires acd_path and/or run_dir.")
    return _run_script("sdk_export_l5x.py", args)


@mcp.tool()
def allen_bradley_sdk_import_l5x(
    l5x_path: str,
    run_dir: str | None = None,
    acd_path: str | None = None,
    xpath: str | None = None,
) -> str:
    """Windows + Logix Designer SDK: partial_import_from_xml_file — merge an L5X fragment (tags, routines, modules, etc.) into `.acd`. Default XPath Controller/Tags; use scoped XPath for programs/routines."""
    l5x = (l5x_path or "").strip()
    if not l5x:
        raise ToolError("allen_bradley_sdk_import_l5x requires l5x_path.")
    args = ["--l5x", l5x]
    rd = (run_dir or "").strip()
    acd = (acd_path or "").strip()
    xp = (xpath or "").strip()
    if rd:
        args += ["--run-dir", rd]
    if acd:
        args += ["--acd", acd]
    if xp:
        args += ["--xpath", xp]
    if not rd and not acd:
        raise ToolError("allen_bradley_sdk_import_l5x requires run_dir and/or acd_path.")
    return _run_script("sdk_import_l5x.py", args)


if __name__ == "__main__":
    mcp.run()