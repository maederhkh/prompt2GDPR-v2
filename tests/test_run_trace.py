"""Standalone assert tests for the RunTrace execution-timeline recorder."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.run_trace import RunTrace


class FakeClock:
    """Deterministic clock: returns scripted increasing values, one per call."""
    def __init__(self, values):
        self._it = iter(values)

    def __call__(self):
        return next(self._it)


def test_two_steps_record_order_durations_status():
    # step() calls the clock twice (start, end): two steps -> four values.
    trace = RunTrace(clock=FakeClock([0.0, 2.0, 2.0, 5.0]))
    with trace.step("extractor", model="m1"):
        pass
    with trace.step("verifier"):
        pass
    events = trace.events
    assert len(events) == 2, events
    assert events[0]["step"] == 1 and events[1]["step"] == 2
    assert events[0]["stage"] == "extractor" and events[0]["model"] == "m1"
    assert events[0]["duration_s"] == 2.0, events[0]
    assert events[1]["stage"] == "verifier" and events[1]["duration_s"] == 3.0
    assert events[0]["status"] == "ok" and events[1]["status"] == "ok"


def test_mark_last_overrides_only_latest():
    trace = RunTrace(clock=FakeClock([0.0, 1.0, 1.0, 2.0]))
    with trace.step("extractor", model="m1"):
        pass
    trace.mark_last(status="fallback", note="single-pass fallback (no Scout)")
    with trace.step("verifier"):
        pass
    events = trace.events
    assert events[0]["status"] == "fallback"
    assert events[0]["note"] == "single-pass fallback (no Scout)"
    assert events[1]["status"] == "ok" and events[1]["note"] == ""


def test_step_records_error_and_reraises():
    trace = RunTrace(clock=FakeClock([0.0, 4.0]))
    raised = False
    try:
        with trace.step("evaluator", model="m2"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised, "step() must re-raise the body's exception"
    events = trace.events
    assert len(events) == 1
    assert events[0]["status"] == "error"
    assert "ValueError" in events[0]["note"] and "boom" in events[0]["note"]
    assert events[0]["duration_s"] == 4.0


def test_non_llm_step_has_none_model():
    trace = RunTrace(clock=FakeClock([0.0, 0.5]))
    with trace.step("merge"):
        pass
    assert trace.events[0]["model"] is None
    assert trace.events[0]["duration_s"] == 0.5


if __name__ == "__main__":
    test_two_steps_record_order_durations_status()
    test_mark_last_overrides_only_latest()
    test_step_records_error_and_reraises()
    test_non_llm_step_has_none_model()
    print("OK")
