#!/usr/bin/env python3
"""Shared JSON stdout helpers for sylo-allen-bradley (SDK) scripts."""

from __future__ import annotations

import json
import sys
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    """Print JSON to stdout and exit with code 0 or 1."""
    print(json.dumps(payload, indent=2))
    if payload.get("ok") is False:
        sys.exit(1)


def emit_error(message: str, **extra: Any) -> None:
    emit({"ok": False, "error": message, **extra})
