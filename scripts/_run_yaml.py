#!/usr/bin/env python3
"""Read/write run.yaml (YAML if PyYAML installed, else JSON)."""

from __future__ import annotations

import json
from pathlib import Path


def _parse_simple_yaml(raw: str) -> dict:
    out: dict = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


def read_run_yaml(run_dir: Path) -> dict:
    path = run_dir / "run.yaml"
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:
        pass
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return _parse_simple_yaml(raw)


def find_working_acd(run_dir: Path) -> Path | None:
    """Working ACD for a run: run.yaml working_acd → working/*.acd → legacy working/project.acd."""
    data = read_run_yaml(run_dir)
    recorded = data.get("working_acd")
    if isinstance(recorded, str) and recorded.strip():
        p = Path(recorded).expanduser()
        if p.is_file():
            return p.resolve()
    working = run_dir / "working"
    if working.is_dir():
        acds = sorted(p for p in working.iterdir() if p.is_file() and p.suffix.lower() == ".acd")
        if len(acds) == 1:
            return acds[0].resolve()
        legacy = working / "project.acd"
        if legacy.is_file():
            return legacy.resolve()
        if acds:
            dev = [p for p in acds if p.stem.lower().endswith(".dev")]
            if len(dev) == 1:
                return dev[0].resolve()
    return None


def write_run_yaml(run_dir: Path, patch: dict) -> None:
    path = run_dir / "run.yaml"
    data = read_run_yaml(run_dir)
    data.update(patch)
    try:
        import yaml  # type: ignore

        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except ImportError:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
