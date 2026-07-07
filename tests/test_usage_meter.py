"""Standalone assert tests for the UsageMeter + MeteredClient."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.usage_meter import UsageMeter, MeteredClient

_MISSING = object()


class _Usage:
    """Fake response.usage. Omit `cost` to simulate a provider that reports none."""
    def __init__(self, prompt_tokens, completion_tokens, total_tokens, cost=_MISSING):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        if cost is not _MISSING:
            self.cost = cost


class _Response:
    def __init__(self, usage):
        self.usage = usage


class _FakeCompletions:
    """Records the kwargs of each call and returns scripted responses in order."""
    def __init__(self, responses):
        self._it = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._it)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def test_records_call_under_active_stage_and_returns_response_unchanged():
    resp = _Response(_Usage(10, 20, 30, cost=0.001))
    client = _FakeClient([resp])
    meter = UsageMeter()
    metered = MeteredClient(client, meter)

    with meter.stage("evaluator"):
        got = metered.chat.completions.create(model="m1", messages=[{"role": "user", "content": "x"}])

    assert got is resp, "response must be returned unchanged"
    assert len(meter.records) == 1
    rec = meter.records[0]
    assert rec["stage"] == "evaluator"
    assert rec["model"] == "m1"
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 20 and rec["total_tokens"] == 30
    assert rec["cost"] == 0.001
    # the usage.include flag was injected into the request
    assert client.chat.completions.calls[0]["extra_body"]["usage"]["include"] is True


def test_by_stage_rolls_up_multiple_calls():
    responses = [_Response(_Usage(5, 5, 10, cost=0.001)), _Response(_Usage(7, 3, 10, cost=0.002))]
    client = _FakeClient(responses)
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("extractor"):
        metered.chat.completions.create(model="scout-model", messages=[])
        metered.chat.completions.create(model="extractor-model", messages=[])

    by_stage = meter.by_stage()
    assert len(by_stage) == 1
    e = by_stage[0]
    assert e["stage"] == "extractor" and e["calls"] == 2
    assert e["total_tokens"] == 20
    assert abs(e["cost"] - 0.003) < 1e-9


def test_merges_existing_extra_body():
    client = _FakeClient([_Response(_Usage(1, 1, 2, cost=0.0))])
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("finalizer"):
        metered.chat.completions.create(model="m", messages=[], extra_body={"foo": 1})
    sent = client.chat.completions.calls[0]["extra_body"]
    assert sent["foo"] == 1                      # caller's key preserved
    assert sent["usage"]["include"] is True      # our flag added


def test_missing_cost_records_none_and_does_not_crash():
    client = _FakeClient([_Response(_Usage(4, 6, 10))])   # no cost attribute
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("reflector_a"):
        metered.chat.completions.create(model="m", messages=[])
    assert meter.records[0]["cost"] is None
    assert meter.by_stage()[0]["cost"] is None
    assert meter.totals()["cost"] is None


def test_totals_and_to_dict():
    responses = [_Response(_Usage(5, 5, 10, cost=0.001)), _Response(_Usage(7, 3, 10, cost=0.002))]
    client = _FakeClient(responses)
    meter = UsageMeter()
    metered = MeteredClient(client, meter)
    with meter.stage("extractor"):
        metered.chat.completions.create(model="a", messages=[])
    with meter.stage("evaluator"):
        metered.chat.completions.create(model="b", messages=[])

    totals = meter.totals()
    assert totals["calls"] == 2 and totals["total_tokens"] == 20
    assert abs(totals["cost"] - 0.003) < 1e-9

    d = meter.to_dict()
    assert set(d.keys()) == {"calls", "by_stage", "totals"}
    assert len(d["calls"]) == 2 and len(d["by_stage"]) == 2


if __name__ == "__main__":
    test_records_call_under_active_stage_and_returns_response_unchanged()
    test_by_stage_rolls_up_multiple_calls()
    test_merges_existing_extra_body()
    test_missing_cost_records_none_and_does_not_crash()
    test_totals_and_to_dict()
    print("OK")
