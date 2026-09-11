#!/usr/bin/env python3
"""Locate and import Rockwell logix_designer_sdk (Windows + local wheel)."""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def wheel_candidates() -> list[Path]:
    out: list[Path] = []
    env_wheel = os.environ.get("LOGIX_DESIGNER_SDK_WHEEL", "").strip()
    if env_wheel:
        out.append(Path(env_wheel).expanduser())

    root = package_root()
    # LogicForge vendor (incl. the SDK wheel drop-spot) moved to the sibling
    # sylo-logicforge package (2026-09-09 split); search it first, then legacy.
    try:
        lf_vendor = root.parents[0] / "sylo-logicforge" / "vendor" / "logicforge"
        if lf_vendor.is_dir():
            out.extend(Path(p) for p in glob.glob(str(lf_vendor / "Studio5000 SDK" / "logix_designer_sdk-*.whl")))
            out.extend(Path(p) for p in glob.glob(str(lf_vendor / "logix_designer_sdk-*.whl")))
    except (OSError, RuntimeError):
        pass
    vendor = root / "vendor" / "logicforge"
    out.extend(Path(p) for p in glob.glob(str(vendor / "Studio5000 SDK" / "logix_designer_sdk-*.whl")))
    out.extend(Path(p) for p in glob.glob(str(vendor / "logix_designer_sdk-*.whl")))

    # Sibling private checkout: ~/Documents/GitHub/sylo-allen-bradley/
    try:
        sib = root.parents[2] / "sylo-allen-bradley"
        out.extend(Path(p) for p in glob.glob(str(sib / "logix_designer_sdk-*.whl")))
    except IndexError:
        pass
    lf_source = os.environ.get("LOGICFORGE_SOURCE", "").strip()
    if lf_source:
        lf = Path(lf_source)
        out.extend(Path(p) for p in glob.glob(str(lf / "Studio5000 SDK" / "logix_designer_sdk-*.whl")))

    pf86 = Path(r"C:\Program Files (x86)\Rockwell Software")
    pub_docs = Path(r"C:\Users\Public\Documents\Studio 5000\Logix Designer SDK\python")
    for pattern in (
        str(pf86 / "Studio 5000" / "Logix Designer SDK" / "Python" / "logix_designer_sdk-*.whl"),
        str(pf86 / "Logix Designer SDK" / "Python" / "logix_designer_sdk-*.whl"),
        str(pub_docs / "logix_designer_sdk-*.whl"),
    ):
        out.extend(Path(p) for p in glob.glob(pattern))

    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def sdk_site_candidates() -> list[Path]:
    """Unpacked SDK trees (e.g. project .venv-libs/logix_designer_sdk)."""
    out: list[Path] = []
    env_site = os.environ.get("LOGIX_DESIGNER_SDK_SITE", "").strip()
    if env_site:
        out.append(Path(env_site).expanduser())

    for key in ("SYLO_PROJECT_DIR", "LOGICFORGE_PROJECT_DIR"):
        project = os.environ.get(key, "").strip()
        if project:
            out.append(Path(project).expanduser() / ".venv-libs" / "logix_designer_sdk")

    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        if not p.is_dir():
            continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def prepend_sdk_site_paths() -> str | None:
    for site in sdk_site_candidates():
        site_str = str(site.resolve())
        if site_str not in sys.path:
            sys.path.insert(0, site_str)
        return site_str
    return None


def resolve_sdk_python() -> str:
    """SDK wheel requires Python 3.12.x (>=3.12,<3.13)."""
    sdk_env = os.environ.get("SYLO_SDK_PYTHON", "").strip()
    if sdk_env:
        return sdk_env

    if sys.version_info.major == 3 and sys.version_info.minor == 12:
        return sys.executable

    if sys.platform == "win32":
        for launcher_args in (["py", "-3.12"], ["py", "-3.12-64"]):
            try:
                result = subprocess.run(
                    [*launcher_args, "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                )
                exe = result.stdout.strip()
                if exe:
                    return exe
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue

    raise RuntimeError(
        "Logix Designer SDK requires Python 3.12.x (>=3.12,<3.13). "
        "SYLO_PYTHON may point at 3.11 for general Sylo scripts — set SYLO_SDK_PYTHON to a 3.12 "
        "python.exe, install with py install 3.12, or run SDK scripts via py -3.12."
    )


def ensure_logix_designer_sdk() -> str:
    """Import logix_designer_sdk; pip-install from wheel if needed. Returns wheel/site path used."""
    site = prepend_sdk_site_paths()
    try:
        import logix_designer_sdk  # noqa: F401

        return site or "already_importable"
    except ImportError:
        pass

    wheels = [p for p in wheel_candidates() if p.is_file()]
    if not wheels:
        raise RuntimeError(
            "logix_designer_sdk not found. Install Logix Designer SDK with Studio 5000, then set "
            "LOGIX_DESIGNER_SDK_WHEEL to the logix_designer_sdk-*.whl path, or clone the private "
            "sylo-allen-bradley repo next to the other Sylo tool repos (~/Documents/GitHub/sylo-allen-bradley). "
            "Optionally unpack the wheel under "
            "<project>/.venv-libs/logix_designer_sdk and set LOGIX_DESIGNER_SDK_SITE."
        )

    if not (sys.version_info.major == 3 and sys.version_info.minor == 12):
        raise RuntimeError(
            "logix_designer_sdk must be installed with Python 3.12.x. "
            f"Current: {sys.version_info.major}.{sys.version_info.minor}. "
            "Set SYLO_PYTHON or re-run with py -3.12."
        )

    wheel = wheels[0]
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", str(wheel), "--quiet"],
        stdout=subprocess.DEVNULL,
    )
    import logix_designer_sdk  # noqa: F401

    return str(wheel)


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Logix Designer SDK export requires Windows with Studio 5000 SDK installed.")
