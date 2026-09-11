#!/usr/bin/env python3
"""Online PLC helpers — upload-from-controller only (no download-to-PLC)."""

from __future__ import annotations

import re
from pathlib import Path

from _sdk_import import sdk_logs_to_stderr


_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def normalize_comm_path(ip_or_path: str) -> str:
    """Accept bare IPv4 or a full Rockwell communications path."""
    raw = ip_or_path.strip()
    if not raw:
        raise ValueError("communications path is empty")
    if "\\" in raw or "/" in raw:
        return raw.replace("/", "\\")
    if _IPV4_RE.match(raw):
        return raw
    return raw


def acd_name_for_comm_path(comm_path: str) -> str:
    """Stable working filename stem from IP or comm path."""
    if _IPV4_RE.match(comm_path):
        return f"PLC_{comm_path.replace('.', '_')}"
    tail = comm_path.replace("\\", "_").replace("/", "_")
    return f"PLC_{tail}"[:80]


async def upload_from_plc_to_acd(acd_path: Path, comm_path: str) -> None:
    """Pull project from controller into a new offline .acd file."""
    from logix_designer_sdk import LogixProject, StdOutEventLogger

    acd_path.parent.mkdir(parents=True, exist_ok=True)
    with sdk_logs_to_stderr():
        await LogixProject.upload_to_new_project(
            str(acd_path),
            comm_path,
            StdOutEventLogger(),
        )
