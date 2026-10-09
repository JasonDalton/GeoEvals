"""Whole-run peak memory: the summed RSS of the runner process and its adapter workers."""

import threading
from types import TracebackType
from typing import Self

import psutil

SAMPLE_INTERVAL_S = 0.05


def _tree_rss(process: psutil.Process) -> int:
    """RSS of ``process`` plus all of its live descendants, in bytes."""
    total = 0
    try:
        members = [process, *process.children(recursive=True)]
    except psutil.Error:
        return 0
    for member in members:
        try:
            total += member.memory_info().rss
        except psutil.Error:  # the process exited or cannot be read
            continue
    return total


class RssSampler:
    """Sample the process tree's RSS on a background thread while the context is active.

    ``peak_rss_bytes`` is the largest sample. Short spikes between samples are missed, so the
    figure is a lower bound on the true peak.
    """

    def __init__(self, interval_s: float = SAMPLE_INTERVAL_S) -> None:
        self._interval_s = interval_s
        self._process = psutil.Process()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rss-sampler", daemon=True)
        self.peak_rss_bytes = 0

    def sample(self) -> None:
        self.peak_rss_bytes = max(self.peak_rss_bytes, _tree_rss(self._process))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.sample()

    def __enter__(self) -> Self:
        self.sample()
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()
        self.sample()
