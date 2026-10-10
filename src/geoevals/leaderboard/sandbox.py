"""The Docker sandbox of the python track: one container per case, with no network.

The image ``geoevals-sandbox:<hash>`` is ``python:3.12-slim`` plus the project's locked runtime
dependencies (``uv export --frozen --no-dev --extra network``: GeoPandas, Shapely, pyproj,
NetworkX, SciPy). The hash covers ``uv.lock`` and the Dockerfile, so a dependency change gives
a new image. The image holds no credentials and no project source.

A container runs ``sleep infinity`` with no network, a read-only root filesystem, a writable
``tmpfs`` at ``/tmp``, CPU, memory and process limits, all capabilities dropped, a non-root
user, and only the benchmark's ``fixtures/`` directory mounted, read-only, at
``/bench/fixtures``. The working directory is ``/bench``, so the case's relative file paths
work. Case files and expected outputs are never mounted. Code runs with ``docker exec``, one
new Python process per call, under a time limit.
"""

import contextlib
import hashlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MOUNT = "/bench"
FIXTURES_MOUNT = f"{MOUNT}/fixtures"
DOCKERFILE = Path(__file__).parent / "sandbox.Dockerfile"
IMAGE_REPOSITORY = "geoevals-sandbox"
LABEL = "geoevals.sandbox=1"
TRUNCATION_MARKER = "\n[... output truncated at {limit} characters ...]"
RUN_LIMITS = [
    "--network",
    "none",
    "--read-only",
    "--tmpfs",
    "/tmp:rw,size=512m",
    "--memory",
    "2g",
    "--cpus",
    "2",
    "--pids-limit",
    "256",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    "--user",
    "65534:65534",
]


class SandboxError(RuntimeError):
    """Docker could not build the image or start the container."""


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def _docker(
    *args: str, timeout: float = 120, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def docker_available() -> bool:
    """Whether the Docker CLI is installed and its daemon answers."""
    if shutil.which("docker") is None:
        return False
    try:
        return _docker("info", "--format", "{{.ServerVersion}}", timeout=30).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def repo_root() -> Path:
    """The repository checkout this package runs from (it holds ``uv.lock``)."""
    root = Path(__file__).resolve().parents[3]
    if not (root / "uv.lock").is_file():
        raise SandboxError(
            f"the python track runs from a repository checkout; no uv.lock in {root}"
        )
    return root


def image_tag(root: Path) -> str:
    """``geoevals-sandbox:<first 12 hex of SHA-256 of uv.lock and the Dockerfile>``."""
    digest = hashlib.sha256()
    digest.update((root / "uv.lock").read_bytes())
    digest.update(DOCKERFILE.read_bytes())
    return f"{IMAGE_REPOSITORY}:{digest.hexdigest()[:12]}"


def ensure_image(root: Path | None = None) -> str:
    """The sandbox image tag, building the image first when it does not exist."""
    root = root or repo_root()
    tag = image_tag(root)
    if _docker("image", "inspect", tag, timeout=60).returncode == 0:
        return tag
    with tempfile.TemporaryDirectory(prefix="geoevals-sandbox-") as context:
        exported = subprocess.run(
            ["uv", "export", "--frozen", "--no-dev", "--extra", "network", "--no-emit-project"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if exported.returncode != 0:
            raise SandboxError(f"uv export failed: {exported.stderr.strip()}")
        (Path(context) / "requirements.txt").write_text(exported.stdout, encoding="utf-8")
        shutil.copy(DOCKERFILE, Path(context) / "Dockerfile")
        built = _docker("build", "--label", LABEL, "-t", tag, context, timeout=1800)
        if built.returncode != 0:
            raise SandboxError(f"docker build failed: {built.stderr.strip()[-4000:]}")
    return tag


def start_container(image: str, name: str, fixtures: Path | None) -> None:
    """Start the case's container. ``fixtures`` is mounted read-only at ``/bench/fixtures``."""
    args = ["run", "-d", "--rm", "--name", name, "--label", LABEL, *RUN_LIMITS]
    args += ["-e", "HOME=/tmp", "-e", "MPLCONFIGDIR=/tmp", "-w", MOUNT]
    if fixtures is not None:
        args += ["-v", f"{fixtures.resolve()}:{FIXTURES_MOUNT}:ro"]
    started = _docker(*args, image, "sleep", "infinity")
    if started.returncode != 0:
        raise SandboxError(f"docker run failed: {started.stderr.strip()}")


def truncate(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` characters, with a marker when it was cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + TRUNCATION_MARKER.format(limit=limit)


def exec_python(
    name: str, code: str, timeout_s: float = 60, max_output: int = 20_000
) -> ExecResult:
    """Run ``code`` with ``python -`` in the container, killed after ``timeout_s``."""
    seconds = f"{timeout_s:g}"
    start = time.monotonic()
    try:
        completed = _docker(
            "exec", "-i", name, "timeout", "-s", "KILL", seconds, "python", "-",
            stdin=code,
            timeout=timeout_s + 30,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return ExecResult(-9, "", f"killed after {seconds} s", True)
    elapsed = time.monotonic() - start
    stderr = completed.stderr
    timed_out = completed.returncode == 137 and elapsed >= timeout_s
    if timed_out:
        stderr += f"\nkilled: the {seconds} s time limit was reached"
    elif completed.returncode == 137:
        stderr += "\nkilled: probably the 2 GB memory limit"
    return ExecResult(
        completed.returncode,
        truncate(completed.stdout, max_output),
        truncate(stderr, max_output),
        timed_out,
    )


def remove_container(name: str) -> None:
    """Remove the container if it exists. Never raises."""
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        _docker("rm", "-f", name, timeout=60)
