"""Adapter worker processes that the runner can terminate when a case times out.

Each worker process creates one adapter, calls ``setup`` once, and then serves ``predict`` calls
over a pipe until it is closed. Keeping the adapter in one process means per-instance state (such
as the mock adapter's ``fail_then_succeed`` count) survives retries. A thread-based timeout cannot
stop a stuck call into native code (Shapely, GEOS), so on timeout the runner kills the process and
starts a new one for the next case.

With ``track_memory`` the worker runs ``tracemalloc`` and reports each call's peak allocation.
``tracemalloc`` is per process, so the figure covers only this adapter's ``predict`` call.
"""

import logging
import multiprocessing
import random
import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, Literal

from geoevals.adapters.base import AdapterResponse
from geoevals.adapters.registry import AdapterFactory

logger = logging.getLogger(__name__)

# spawn on every platform: the same behavior on Linux and macOS, and no forked thread state.
_CONTEXT = multiprocessing.get_context("spawn")

AttemptKind = Literal["ok", "error", "timeout"]


class WorkerSetupError(RuntimeError):
    """The adapter could not be created or set up in the worker process."""


@dataclass(frozen=True)
class Attempt:
    """Result of one ``predict`` call.

    ``latency_s`` is the adapter's wall-clock time (the time waited, for a timeout). ``error_type``
    and ``error_message`` are set when ``kind`` is ``error`` or ``timeout``. ``peak_memory_bytes``
    is the peak traced allocation during ``predict`` above what was live when it started; it is
    set only when the worker tracks memory and the call returned or raised.
    """

    kind: AttemptKind
    latency_s: float
    output: Any = None
    tokens: tuple[int, int] | None = None
    trajectory: list[dict[str, Any]] | None = None
    error_type: str | None = None
    error_message: str | None = None
    peak_memory_bytes: int | None = None


def _serve(
    conn: Connection, factory: AdapterFactory, config: Mapping[str, Any], track_memory: bool
) -> None:
    """Worker process entry point."""
    try:
        adapter = factory()
        adapter.setup(config)
    except BaseException as exc:
        conn.send(("setup_error", type(exc).__name__, str(exc)))
        return
    if track_memory:
        tracemalloc.start()
    conn.send(("ready",))
    try:
        while True:
            try:
                message = conn.recv()
            except EOFError:
                return
            if message is None:
                return
            case_input, seed = message
            random.seed(seed)
            baseline = 0
            if track_memory:
                tracemalloc.reset_peak()
                baseline = tracemalloc.get_traced_memory()[0]
            start = time.perf_counter()
            try:
                response = adapter.predict(case_input)
            except Exception as exc:
                elapsed = time.perf_counter() - start
                peak = _peak_since(baseline) if track_memory else None
                conn.send(("error", elapsed, peak, type(exc).__name__, str(exc)))
                continue
            elapsed = time.perf_counter() - start
            peak = _peak_since(baseline) if track_memory else None
            if not isinstance(response, AdapterResponse):
                kind = type(response).__name__
                message = f"predict returned {kind}, not AdapterResponse"
                conn.send(("error", elapsed, peak, "TypeError", message))
                continue
            tokens = (response.tokens.input, response.tokens.output) if response.tokens else None
            try:
                conn.send(("ok", elapsed, peak, response.output, tokens, response.trajectory))
            except Exception as exc:  # the response could not be pickled
                message = f"unsendable response: {exc}"
                conn.send(("error", elapsed, peak, type(exc).__name__, message))
    finally:
        adapter.teardown()


def _peak_since(baseline: int) -> int:
    return max(tracemalloc.get_traced_memory()[1] - baseline, 0)


class Worker:
    """One adapter in its own process. Not thread-safe: use each worker from one thread."""

    def __init__(
        self, factory: AdapterFactory, config: Mapping[str, Any], track_memory: bool = False
    ) -> None:
        self._factory = factory
        self._config = dict(config)
        self._track_memory = track_memory
        self._process: Any = None
        self._conn: Connection | None = None

    def _start(self) -> Connection:
        parent, child = _CONTEXT.Pipe()
        process = _CONTEXT.Process(
            target=_serve,
            args=(child, self._factory, self._config, self._track_memory),
            daemon=True,
        )
        process.start()
        child.close()
        try:
            message = parent.recv()
        except EOFError:
            process.join()
            raise WorkerSetupError(
                f"adapter worker exited during setup (exit code {process.exitcode})"
            ) from None
        if message[0] == "setup_error":
            process.join()
            raise WorkerSetupError(f"adapter setup failed: {message[1]}: {message[2]}")
        logger.debug("started adapter worker pid %s", process.pid)
        self._process, self._conn = process, parent
        return parent

    def _kill(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.join()
            logger.debug("killed adapter worker pid %s", self._process.pid)
        if self._conn is not None:
            self._conn.close()
        self._process, self._conn = None, None

    def predict(self, case_input: Mapping[str, Any], seed: str, timeout_s: float) -> Attempt:
        """Run one ``predict`` call. Kills the process if it takes longer than ``timeout_s``."""
        conn = self._conn or self._start()
        start = time.perf_counter()
        conn.send((dict(case_input), seed))
        if not conn.poll(timeout_s):
            waited = time.perf_counter() - start
            self._kill()
            message = f"case exceeded timeout_s={timeout_s:g}"
            return Attempt("timeout", waited, error_type="TimeoutError", error_message=message)
        try:
            message = conn.recv()
        except EOFError:
            waited = time.perf_counter() - start
            exitcode = self._process.exitcode if self._process is not None else None
            self._kill()
            return Attempt(
                "error",
                waited,
                error_type="WorkerCrashed",
                error_message=f"adapter worker exited during predict (exit code {exitcode})",
            )
        if message[0] == "error":
            _, latency, peak, error_type, error_message = message
            return Attempt(
                "error",
                latency,
                error_type=error_type,
                error_message=error_message,
                peak_memory_bytes=peak,
            )
        _, latency, peak, output, tokens, trajectory = message
        return Attempt(
            "ok",
            latency,
            output=output,
            tokens=tokens,
            trajectory=trajectory,
            peak_memory_bytes=peak,
        )

    def close(self) -> None:
        """Stop the process, letting the adapter run ``teardown``."""
        if self._conn is None:
            return
        try:
            self._conn.send(None)
            self._process.join(timeout=5)
        except (BrokenPipeError, OSError):
            pass
        self._kill()
