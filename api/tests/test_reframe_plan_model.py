"""Tests for the strongly-typed reframe plan model + EXPLAIN printer."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from reframe_plan_model import (  # noqa: E402
    CropSource,
    DecisionStatus,
    EscalationKind,
    Layout,
    ReframePlan,
    Segment,
)


def _seg(start, end, inner_ar, source="face", coverage=1.0, layout="single", esc=None):
    return {
        "start": start,
        "end": end,
        "layout": layout,
        "inner_ar": inner_ar,
        "reason": f"{source} seg",
        "trace": {"source": source, "coverage": coverage, "n_faces": 1},
        "escalate": esc,
    }


def _record(segs, canvas="9:16"):
    return {
        "id": "rf-test",
        "output_aspect_ratio": canvas,
        "eval_report": {"meta": {"src_w": 1280, "src_h": 720}},
        "segment_plan": segs,
    }


class TestParsing:
    def test_dims_from_meta_and_duration_from_last_end(self):
        plan = ReframePlan.from_dict(
            _record([_seg(0, 4, [9, 16]), _seg(4, 9, [16, 9])])
        )
        assert (plan.src_w, plan.src_h) == (1280, 720)
        assert plan.duration == 9.0
        assert plan.canvas == "9:16"

    def test_missing_dims_raises(self):
        rec = _record([_seg(0, 4, [9, 16])])
        rec["eval_report"] = {}
        with pytest.raises(ValueError):
            ReframePlan.from_dict(rec)

    def test_explicit_dims_override(self):
        rec = _record([_seg(0, 4, [9, 16])])
        rec["eval_report"] = {}
        plan = ReframePlan.from_dict(rec, src_w=1920, src_h=1080)
        assert plan.src_w == 1920

    def test_enums_coerced(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [9, 16], source="speaker")]))
        s = plan.segments[0]
        assert s.layout is Layout.SINGLE
        assert s.source is CropSource.SPEAKER

    def test_unknown_source_degrades(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [9, 16], source="bogus")]))
        assert plan.segments[0].source is CropSource.UNKNOWN


class TestLetterboxFlag:
    # The crux: full source-width (16:9) is the MOST letterboxed on a portrait
    # canvas; the tight 9:16 rung is full-bleed. cov is the inverse of letterbox.
    def test_full_bleed_rung_not_letterboxed(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [9, 16], coverage=0.32)]))
        assert plan.segments[0].letterboxed is False

    def test_wide_rung_is_letterboxed(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [16, 9], coverage=1.0)]))
        assert plan.segments[0].letterboxed is True

    def test_split_never_letterboxed(self):
        plan = ReframePlan.from_dict(
            _record([_seg(0, 4, None, layout="split", coverage=1.0)])
        )
        assert plan.segments[0].letterboxed is False

    def test_three_four_canvas_full_bleed(self):
        plan = ReframePlan.from_dict(
            _record([_seg(0, 4, [3, 4], coverage=0.5)], canvas="3:4")
        )
        assert plan.segments[0].letterboxed is False


class TestEscalation:
    def _esc(self):
        return {
            "kind": "text_presence",
            "key": "text:left:0.0-1.0@0.5",
            "question": "caption or background?",
            "facts": {"side": "left"},
            "fallback": {"action": "crop"},
        }

    def test_escalation_parsed_and_status(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [9, 16], esc=self._esc())]))
        s = plan.segments[0]
        assert s.status is DecisionStatus.ESCALATED
        assert s.escalation.kind is EscalationKind.TEXT_PRESENCE
        assert plan.escalated == [s]

    def test_no_escalation_is_resolved(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [9, 16])]))
        assert plan.segments[0].status is DecisionStatus.RESOLVED
        assert plan.escalated == []

    def test_batch_plan_built_from_escalations(self):
        plan = ReframePlan.from_dict(
            _record([_seg(0, 4, [9, 16], esc=self._esc()), _seg(4, 8, [9, 16])])
        )
        bp = plan.batch_plan()
        assert bp["n_points"] == 1 and bp["n_calls"] == 1


class TestExplain:
    def test_explain_lists_every_segment_and_escalation(self):
        plan = ReframePlan.from_dict(
            _record(
                [
                    _seg(0, 4, [9, 16]),
                    _seg(
                        4,
                        8,
                        [9, 16],
                        esc={
                            "kind": "text_presence",
                            "key": "k",
                            "question": "caption?",
                            "facts": {},
                            "fallback": {"action": "crop"},
                        },
                    ),
                ]
            )
        )
        out = plan.explain()
        assert "2 segments" in out
        assert "text_presence" in out
        assert "⚡" in out  # escalation footer marker


class TestRoundTrip:
    def test_to_dict_preserves_core_fields(self):
        plan = ReframePlan.from_dict(_record([_seg(0, 4, [16, 9], source="person")]))
        d = plan.to_dict()
        assert d["segments"][0]["inner_ar"] == [16, 9]
        assert d["segments"][0]["source"] == "person"

    def test_segment_from_dict_index(self):
        s = Segment.from_dict(_seg(1, 2, [9, 16]), index=7)
        assert s.index == 7
