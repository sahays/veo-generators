"""Pass-2 orchestration loop tests (ReframeProcessor._apply_gemini_decisions).

apply_verdicts is unit-tested elsewhere; this exercises the GLUE that wires the
planner's escalations to the decision model and back:

    collect_escalation_points → plan_batches → ai_svc.decide_escalations → apply_verdicts

The whole design rests on one invariant — the plan is always renderable whether or
not Gemini runs — so we assert the fallback survives when the call fails, when a
verdict is missing, and that only matched keys change. The model is mocked; no
network, no ffmpeg.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "workers"))

from reframe_escalation import make_point  # noqa: E402
from reframe_plan import RUNGS  # noqa: E402

SRC_W, SRC_H = 1920, 1080


def _text_seg(key, cov=0.9, start=0.0, end=6.0):
    """A text_presence-escalated segment with a well-formed make_point payload."""
    esc = make_point(
        kind="text_presence",
        key=key,
        question="readable side text or just background?",
        facts={"text_coverage": cov, "crop_keeps": [0.3, 0.7], "check_side": "left"},
        fallback={"action": "crop"},
        start=start,
        end=end,
    )
    return {
        "start": start,
        "end": end,
        "inner_ar": (9, 16),
        "layout": "single",
        "reason": "9:16 — face",
        "trace": {"source": "face", "chosen_ar": [9, 16], "coverage": 0.316},
        "crops": [
            {
                "track_id": 1,
                "x_target": 0.5,
                "source": "face",
                "keypoints": [(start, 0.5, 0.5), (end, 0.5, 0.5)],
            }
        ],
        "escalate": esc,
    }


def _plain_seg(start=0.0, end=3.0):
    return {
        "start": start,
        "end": end,
        "inner_ar": (9, 16),
        "layout": "single",
        "reason": "9:16 — face",
        "crops": [{"track_id": 1, "x_target": 0.5, "source": "face"}],
    }


def _make_processor(monkeypatch, decide_impl):
    """A ReframeProcessor with deps/cost stubbed and a mocked decision model.

    `decide_impl(batches, src_path, region)` is the async body the fake
    ai_svc.decide_escalations runs. Returns (processor, cost_calls list).
    """
    import deps
    from reframe_processor import ReframeProcessor

    monkeypatch.setattr(deps, "firestore_svc", MagicMock())

    async def _decide(batches, src_path, region=None, canvas="9:16"):
        return await decide_impl(batches, src_path, region)

    monkeypatch.setattr(deps, "ai_svc", SimpleNamespace(decide_escalations=_decide))

    cost_calls = []
    import reframe_processor

    monkeypatch.setattr(
        reframe_processor,
        "accumulate_text_cost_on",
        lambda *a, **k: cost_calls.append((a, k)),
    )
    return ReframeProcessor(), cost_calls


def _apply(proc, segments, tracked=None):
    proc._apply_gemini_decisions(
        record=SimpleNamespace(region=None),
        record_id="rf-test",
        segments=segments,
        src_path="/nonexistent.mp4",
        src_w=SRC_W,
        src_h=SRC_H,
        rungs=RUNGS,
        tracked_frames=tracked,
        person_frames=None,
    )


def _result(verdicts, cost=0.0):
    return SimpleNamespace(
        data={"verdicts": verdicts},
        usage=SimpleNamespace(
            cost_usd=cost,
            input_tokens=10,
            output_tokens=5,
            model_name="gemini-3.5-flash",
        ),
    )


class TestOrchestration:
    def test_no_escalations_skips_model_call(self, monkeypatch):
        called = {"n": 0}

        async def decide(batches, src_path, region=None, canvas="9:16"):
            called["n"] += 1
            return _result([])

        proc, _ = _make_processor(monkeypatch, decide)
        segs = [_plain_seg()]
        _apply(proc, segs)
        assert called["n"] == 0  # nothing to decide → no call at all
        assert segs[0]["inner_ar"] == (9, 16)

    def test_model_failure_keeps_every_fallback(self, monkeypatch):
        # The crux invariant: if the decision call blows up, the plan is untouched
        # and fully renderable on its deterministic fallbacks.
        async def decide(batches, src_path, region=None, canvas="9:16"):
            raise RuntimeError("429 / model exploded")

        proc, cost = _make_processor(monkeypatch, decide)
        segs = [_text_seg("text:a"), _text_seg("text:b", start=6.0, end=12.0)]
        _apply(proc, segs)
        assert all(s["inner_ar"] == (9, 16) for s in segs)  # no letterbox applied
        assert all("verdict" not in s["escalate"] for s in segs)  # no verdict stamped
        assert cost == []  # no usage to bill when the call failed

    def test_partial_verdicts_only_matched_keys_change(self, monkeypatch):
        # Verdict returned for shot 'a' (letterbox) but not 'b' → only a changes.
        # The model echoes the per-cluster unique keys it was sent.
        async def decide(batches, src_path, region=None, canvas="9:16"):
            keys = [c["key"] for b in batches for c in b]
            akey = next(k for k in keys if k.startswith("text:a"))
            return _result(
                [{"key": akey, "action": "letterbox", "coverage": 0.9}], cost=0.01
            )

        proc, cost = _make_processor(monkeypatch, decide)
        a = _text_seg("text:a")
        b = _text_seg("text:b", start=6.0, end=12.0)
        _apply(proc, [a, b])
        assert a["inner_ar"] == (16, 9)  # widened to keep side text
        assert a["escalate"]["verdict"]["action"] == "letterbox"
        assert b["inner_ar"] == (9, 16)  # no verdict → fallback (crop)
        assert "verdict" not in b["escalate"]
        assert len(cost) == 1  # usage billed once for the successful call

    def test_crop_verdict_keeps_fallback_but_records_verdict(self, monkeypatch):
        async def decide(batches, src_path, region=None, canvas="9:16"):
            keys = [c["key"] for b in batches for c in b]
            return _result([{"key": k, "action": "crop"} for k in keys], cost=0.01)

        proc, _ = _make_processor(monkeypatch, decide)
        a = _text_seg("text:a")
        _apply(proc, [a])
        assert a["inner_ar"] == (9, 16)  # crop → unchanged
        assert a["escalate"]["verdict"]["action"] == "crop"  # still traced

    def test_distant_same_key_verdict_does_not_bleed(self, monkeypatch):
        # Two shots share the geometric key but sit 20s apart → SEPARATE clusters.
        # A letterbox verdict on the first run must NOT letterbox the distant one
        # (the rf-vlsygfxe bleed: one verdict stamped onto 7 shots video-wide).
        async def decide(batches, src_path, region=None, canvas="9:16"):
            keys = [c["key"] for b in batches for c in b]
            earliest = min(keys, key=lambda k: float(k.split("#t")[1]))
            return _result(
                [{"key": earliest, "action": "letterbox", "coverage": 0.9}], cost=0.01
            )

        proc, _ = _make_processor(monkeypatch, decide)
        s1 = _text_seg("text:dup", start=0.0, end=6.0)
        s2 = _text_seg("text:dup", start=20.0, end=26.0)
        _apply(proc, [s1, s2])
        assert s1["inner_ar"] == (16, 9)  # first run got the verdict
        assert s2["inner_ar"] == (9, 16)  # distant run kept its fallback — no bleed

    def test_zero_cost_usage_not_billed(self, monkeypatch):
        async def decide(batches, src_path, region=None, canvas="9:16"):
            keys = [c["key"] for b in batches for c in b]
            return _result(
                [{"key": k, "action": "letterbox", "coverage": 0.9} for k in keys],
                cost=0.0,
            )

        proc, cost = _make_processor(monkeypatch, decide)
        _apply(proc, [_text_seg("text:a")])
        assert cost == []  # cost_usd == 0 → nothing accumulated
