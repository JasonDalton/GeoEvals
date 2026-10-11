"""Run a command so that it cannot outlive the process that started it.

``python -m geoevals.leaderboard.watchdog [--container NAME] -- <command...>`` starts the command
in its own process group, with stdin, stdout and stderr passed through, and exits with its exit
code. It stops the command's whole group (the Claude Code CLI and the MCP server it started)
and removes the Docker container ``NAME``, if given, when:

- its parent process dies: the runner kills an adapter worker with SIGKILL when a case exceeds
  the run's ``timeout_s``, which the worker cannot catch, so the watchdog polls for it;
- it gets SIGTERM: ``claude_cli.run_cli`` sends it on the adapter's own timeout.
"""

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from types import FrameType

POLL_S = 0.5
SECOND_REMOVAL_DELAY_S = 2.0


def _remove_container(name: str | None) -> None:
    if name is None:
        return
    # A ``docker run`` in flight when the group was killed can still create the container, so
    # remove it twice.
    for attempt in range(2):
        if attempt:
            time.sleep(SECOND_REMOVAL_DELAY_S)
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=60, check=False
            )


def _stop(child: subprocess.Popen[bytes], container: str | None) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=10)
    _remove_container(container)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command that dies with its parent.")
    parser.add_argument("--container", help="Docker container to remove when stopping.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given")
    parent = os.getppid()
    child = subprocess.Popen(command, start_new_session=True)

    def on_term(signum: int, frame: FrameType | None) -> None:
        _stop(child, args.container)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, on_term)
    while True:
        try:
            return child.wait(timeout=POLL_S)
        except subprocess.TimeoutExpired:
            pass
        if os.getppid() != parent:
            _stop(child, args.container)
            return 137


if __name__ == "__main__":
    sys.exit(main())
