#!/usr/bin/env python3
"""Shared download-allowlist loader / membership gate.

The canonical allowlist lives at packages/sylo-logicforge/assets/download-allowlist.json
and is operator-managed via the LogicForge Settings tab. The agent never edits
it — the download script reads it and refuses any IP not present and enabled.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def allowlist_path() -> Path:
    """Allowlist JSON path (env override for project-local testing)."""
    env = os.environ.get("LOGICFORGE_DOWNLOAD_ALLOWLIST", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # Canonical file lives with sylo-logicforge (the LogicForge Settings tab
    # reads/writes it there); resolve across the monorepo so every package
    # enforces the same operator list.
    sibling = (
        Path(__file__).resolve().parents[2]
        / "sylo-logicforge"
        / "assets"
        / "download-allowlist.json"
    )
    if sibling.is_file():
        return sibling
    return package_root() / "assets" / "download-allowlist.json"


def default_allowlist() -> dict[str, Any]:
    return {
        "allow_downloads": False,
        "post_download_mode": "program",
        "ips": [],
        "updated_at": None,
        "notes": "Operator-managed via LogicForge Settings tab.",
    }


def load_allowlist() -> dict[str, Any]:
    path = allowlist_path()
    if not path.is_file():
        return default_allowlist()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_allowlist()
    if not isinstance(data, dict):
        return default_allowlist()
    # Normalize / fill missing keys
    base = default_allowlist()
    base.update(data)
    if not isinstance(base.get("ips"), list):
        base["ips"] = []
    if base.get("post_download_mode") not in ("program", "run"):
        base["post_download_mode"] = "program"
    return base


def save_allowlist(data: dict[str, Any]) -> dict[str, Any]:
    path = allowlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if data.get("post_download_mode") not in ("program", "run"):
        data["post_download_mode"] = "program"
    if not isinstance(data.get("ips"), list):
        data["ips"] = []
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _ip_from_comm_path(comm_path: str) -> str | None:
    """Extract a bare IPv4 from a Rockwell comm path, else None."""
    import re

    raw = comm_path.strip()
    # Look for an IPv4 anywhere in the path
    m = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", raw)
    return m.group(0) if m else None


def check_ip_allowed(ip_or_comm: str, allowlist: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Return (allowed, reason). Resolves bare IP from a comm path if needed."""
    al = allowlist if allowlist is not None else load_allowlist()
    if not al.get("allow_downloads", False):
        return False, "Downloads are disabled in the allowlist (allow_downloads=false)."

    ip = ip_or_comm.strip()
    if "\\" in ip or "/" in ip:
        ip = _ip_from_comm_path(ip) or ip

    for entry in al.get("ips", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("ip") == ip:
            if entry.get("enabled", True):
                return True, ip
            return False, f"IP {ip} is in the allowlist but disabled."
    return False, f"IP {ip} is not in the download allowlist. The agent cannot download to it."