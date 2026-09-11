#!/usr/bin/env python3
"""Shared Logix Designer SDK partial import helper."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path


def sdk_logs_to_stderr():
    """Route SDK StdOutEventLogger output to stderr so stdout stays clean JSON."""
    return contextlib.redirect_stdout(sys.stderr)


async def partial_import_from_l5x(acd_path: Path, xpath: str, fragment_path: Path) -> None:
    from logix_designer_sdk import ImportCollisionOptions, LogixProject, StdOutEventLogger

    with sdk_logs_to_stderr():
        project = await LogixProject.open_logix_project(str(acd_path), StdOutEventLogger())
        await project.partial_import_from_xml_file(
            xpath,
            str(fragment_path),
            ImportCollisionOptions.OVERWRITE_ON_COLL,
        )
        await project.save()
