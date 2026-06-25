"""
Per-run execution-timeline recorder.

RunTrace records one event per pipeline stage: its order, wall-clock duration,
the model used (or None for non-LLM steps), and a status (ok / fallback /
retry / error). The orchestrator wraps each stage call in `with trace.step(...)`.
Pure: no I/O, no knowledge of pipeline data. The clock is injectable so the
recorder is deterministically unit-testable offline.
"""

import time
from contextlib import contextmanager


class RunTrace:
    def __init__(self, clock=time.perf_counter):
        self._clock = clock
        self._events = []

    @contextmanager
    def step(self, stage: str, model=None):
        """
        Time a pipeline stage and record one event.

        Appends the event on entry (so its step number is stable and it is
        recorded even if the body raises). On clean exit: status "ok". On
        exception: status "error" with the exception in the note, then
        re-raises so the orchestrator's existing error handling is unchanged.
        """
        start = self._clock()
        event = {
            "step": len(self._events) + 1,
            "stage": stage,
            "model": model,
            "duration_s": 0.0,
            "status": "ok",
            "note": "",
        }
        self._events.append(event)
        try:
            yield
        except BaseException as exc:
            event["duration_s"] = round(self._clock() - start, 3)
            event["status"] = "error"
            event["note"] = f"{type(exc).__name__}: {exc}"
            raise
        else:
            event["duration_s"] = round(self._clock() - start, 3)

    def mark_last(self, *, status=None, note=None) -> None:
        """Override the most recent event's status and/or note. No-op if empty."""
        if not self._events:
            return
        if status is not None:
            self._events[-1]["status"] = status
        if note is not None:
            self._events[-1]["note"] = note

    @property
    def events(self) -> list:
        """The ordered list of recorded event dicts."""
        return self._events
