"""Environment fingerprint recorded in every run result (``environment``).

Keys (a value is null when it cannot be determined, for example a library that is not
installed or a project directory outside git):

- ``python``, ``python_implementation``, ``os``, ``os_release``, ``platform``, ``machine``
- ``cpu_model``, ``cpu_count_logical``, ``ram_total_bytes``
- ``geoevals_version``, ``shapely_version``, ``pyproj_version``, ``geopandas_version``
- ``geos_version`` (from shapely), ``proj_version`` (from pyproj)
- ``git_commit``, ``git_dirty`` (untracked files count as dirty; ignored files do not)
- ``uv_lock_sha256``: of ``uv.lock`` at the git top level, or in the project directory
  outside git

The project directory is the current working directory unless given.
"""

import hashlib
import importlib
import importlib.metadata
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil

ENVIRONMENT_KEYS = (
    "python",
    "python_implementation",
    "os",
    "os_release",
    "platform",
    "machine",
    "cpu_model",
    "cpu_count_logical",
    "ram_total_bytes",
    "geoevals_version",
    "shapely_version",
    "pyproj_version",
    "geopandas_version",
    "geos_version",
    "proj_version",
    "git_commit",
    "git_dirty",
    "uv_lock_sha256",
)


def _run(*args: str, cwd: Path | None = None) -> str | None:
    """Return the stripped stdout of a command, or None when it fails or is not installed."""
    try:
        done = subprocess.run(
            list(args), cwd=cwd, capture_output=True, text=True, check=False, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def cpu_model() -> str | None:
    if sys.platform == "darwin":
        model = _run("sysctl", "-n", "machdep.cpu.brand_string")
        if model:
            return model
    elif sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(":")
                if key.strip() in ("model name", "Hardware", "Processor") and value.strip():
                    return value.strip()
        except OSError:
            pass
    return platform.processor() or None


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _library_attribute(module: str, attribute: str) -> str | None:
    """Return ``module.attribute`` as a string, or None when the module is not installed."""
    if importlib.util.find_spec(module) is None:
        return None
    try:
        value = getattr(importlib.import_module(module), attribute, None)
    except Exception:
        return None
    return None if value is None else str(value)


def git_state(project_dir: Path) -> tuple[str | None, bool | None]:
    """Return ``(commit, dirty)`` of the git working tree at ``project_dir``, or nulls."""
    commit = _run("git", "-C", str(project_dir), "rev-parse", "HEAD")
    if commit is None:
        return None, None
    status = _run("git", "-C", str(project_dir), "status", "--porcelain")
    return commit, None if status is None else bool(status)


def uv_lock_sha256(project_dir: Path) -> str | None:
    toplevel = _run("git", "-C", str(project_dir), "rev-parse", "--show-toplevel")
    lock = (Path(toplevel) if toplevel else project_dir) / "uv.lock"
    try:
        return hashlib.sha256(lock.read_bytes()).hexdigest()
    except OSError:
        return None


def environment_fingerprint(project_dir: Path | None = None) -> dict[str, Any]:
    """Return the environment fingerprint; see the module docstring for the keys."""
    project_dir = Path.cwd() if project_dir is None else project_dir
    commit, dirty = git_state(project_dir)
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "os": platform.system(),
        "os_release": platform.release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_model(),
        "cpu_count_logical": os.cpu_count(),
        "ram_total_bytes": psutil.virtual_memory().total,
        "geoevals_version": _version("geoevals"),
        "shapely_version": _version("shapely"),
        "pyproj_version": _version("pyproj"),
        "geopandas_version": _version("geopandas"),
        "geos_version": _library_attribute("shapely", "geos_version_string"),
        "proj_version": _library_attribute("pyproj", "proj_version_str"),
        "git_commit": commit,
        "git_dirty": dirty,
        "uv_lock_sha256": uv_lock_sha256(project_dir),
    }
