"""
Per-run token & cost meter.

UsageMeter collects one record per LLM call — the active stage (which agent was
running), the model, token counts, and OpenRouter-reported cost — and rolls
them up per stage and for the whole run. MeteredClient wraps the OpenAI client
so every chat.completions.create call is recorded and OpenRouter's inline cost
is requested; the agents keep calling the client unchanged.

Pure aside from delegating to the wrapped client: it performs no I/O of its own
and never crashes a run — a missing or malformed usage object yields a
zero/None record rather than raising.
"""

from contextlib import contextmanager


class UsageMeter:
    def __init__(self):
        self._records = []
        self._stage = None

    @contextmanager
    def stage(self, name):
        """Mark `name` as the active stage for calls made inside the block.

        Restores the previous stage on exit so sequential/nested stages are safe.
        """
        previous = self._stage
        self._stage = name
        try:
            yield
        finally:
            self._stage = previous

    def record(self, *, model, prompt_tokens, completion_tokens, total_tokens, cost) -> None:
        """Append one per-call record under the currently-active stage."""
        self._records.append({
            "stage": self._stage,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
        })

    @property
    def records(self) -> list:
        return self._records

    def _rollup(self, rows) -> dict:
        agg = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
               "total_tokens": 0, "cost": None}
        for r in rows:
            agg["calls"] += 1
            agg["prompt_tokens"] += r["prompt_tokens"] or 0
            agg["completion_tokens"] += r["completion_tokens"] or 0
            agg["total_tokens"] += r["total_tokens"] or 0
            if r["cost"] is not None:
                agg["cost"] = (agg["cost"] or 0) + r["cost"]
        return agg

    def by_stage(self) -> list:
        """One roll-up entry per stage, in first-seen order."""
        order = []
        buckets = {}
        for r in self._records:
            stage = r["stage"]
            if stage not in buckets:
                buckets[stage] = []
                order.append(stage)
            buckets[stage].append(r)
        result = []
        for stage in order:
            entry = self._rollup(buckets[stage])
            entry["stage"] = stage
            # stage first for readability
            result.append({"stage": stage, **{k: entry[k] for k in
                            ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cost")}})
        return result

    def totals(self) -> dict:
        return self._rollup(self._records)

    def to_dict(self) -> dict:
        return {"calls": self._records, "by_stage": self.by_stage(), "totals": self.totals()}


def _extract_usage(response) -> dict:
    """Read token/cost fields off response.usage, defensively. Never raises."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": None}

    def _int(attr):
        value = getattr(usage, attr, 0)
        return value if isinstance(value, int) else 0

    cost = getattr(usage, "cost", None)
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        cost = None
    return {
        "prompt_tokens": _int("prompt_tokens"),
        "completion_tokens": _int("completion_tokens"),
        "total_tokens": _int("total_tokens"),
        "cost": cost,
    }


class _MeteredCompletions:
    def __init__(self, inner, meter):
        self._inner = inner
        self._meter = meter

    def create(self, **kwargs):
        # Ask OpenRouter to include cost inline, preserving any caller extra_body keys.
        extra_body = dict(kwargs.get("extra_body") or {})
        usage_opt = dict(extra_body.get("usage") or {})
        usage_opt["include"] = True
        extra_body["usage"] = usage_opt
        kwargs["extra_body"] = extra_body

        response = self._inner.create(**kwargs)

        u = _extract_usage(response)
        self._meter.record(model=kwargs.get("model"), **u)
        return response


class _MeteredChat:
    def __init__(self, inner_chat, meter):
        self.completions = _MeteredCompletions(inner_chat.completions, meter)


class MeteredClient:
    """Wraps an OpenAI client so every chat.completions.create is metered.

    Exposes only the surface the agents use (`client.chat.completions.create`).
    """
    def __init__(self, inner_client, meter: UsageMeter):
        self._inner = inner_client
        self.chat = _MeteredChat(inner_client.chat, meter)
