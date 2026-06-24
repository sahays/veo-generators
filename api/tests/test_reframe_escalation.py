"""Tests for the escalation batching spine (reframe_escalation).

Covers the rate-limit discipline: same-entity questions cluster into one call,
clusters chunk into few requests, and an over-budget video drops the
lowest-impact ambiguities (logged, never silent) while keeping the rest on their
deterministic fallback.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_escalation import (  # noqa: E402
    MAX_POINTS_PER_CALL,
    cluster_escalations,
    make_point,
    plan_batches,
    summarize,
)


def _pt(key, start, end, kind="text_presence", thumb=None):
    return make_point(
        kind=kind,
        key=key,
        question="meaningful side text?",
        facts={"span": [0.0, 1.0]},
        fallback={"action": "crop"},
        start=start,
        end=end,
        thumb_sec=thumb,
    )


class TestMakePoint:
    def test_thumb_defaults_to_midpoint(self):
        p = _pt("k", 2.0, 6.0)
        assert p["thumb_sec"] == 4.0

    def test_unknown_kind_rejected(self):
        try:
            make_point("bogus", "k", "q", {}, {}, 0, 1)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestClustering:
    def test_same_key_collapses_to_one_cluster(self):
        # The same two faces across three adjacent segments → one question.
        pts = [_pt("faces:AB", 0, 2), _pt("faces:AB", 2, 4), _pt("faces:AB", 4, 6)]
        clusters = cluster_escalations(pts)
        assert len(clusters) == 1
        c = clusters[0]
        assert c["count"] == 3
        assert c["start"] == 0 and c["end"] == 6
        assert c["impact"] == 6.0  # total covered duration

    def test_distinct_keys_stay_separate_in_first_seen_order(self):
        pts = [_pt("b", 4, 6), _pt("a", 0, 2), _pt("b", 6, 8)]
        keys = [c["key"] for c in cluster_escalations(pts)]
        assert keys == ["b", "a"]  # first-seen order preserved

    def test_thumbs_deduped_and_capped(self):
        pts = [_pt("k", t, t + 2, thumb=1.0) for t in range(0, 12, 2)]
        c = cluster_escalations(pts)[0]
        assert c["thumb_secs"] == [1.0]  # identical thumbs deduped


class TestBatching:
    def test_empty_yields_no_calls(self):
        plan = plan_batches([])
        assert plan["n_calls"] == 0 and plan["batches"] == []

    def test_chunks_by_max_points(self):
        pts = [_pt(f"k{i}", i, i + 1) for i in range(MAX_POINTS_PER_CALL + 3)]
        plan = plan_batches(pts)
        assert plan["n_calls"] == 2
        assert len(plan["batches"][0]) == MAX_POINTS_PER_CALL
        assert len(plan["batches"][1]) == 3

    def test_clustering_reduces_call_count(self):
        # 20 segments but only 2 distinct questions → a single call, not three.
        pts = [_pt("A", i, i + 1) for i in range(10)] + [
            _pt("B", 10 + i, 11 + i) for i in range(10)
        ]
        plan = plan_batches(pts)
        assert plan["n_clusters"] == 2
        assert plan["n_calls"] == 1

    def test_over_budget_drops_lowest_impact_and_keeps_time_order(self):
        # Tiny budget: 1 call × 2 points = cap 2. Three distinct questions; the
        # shortest (lowest-impact) is dropped, kept set stays in time order.
        pts = [
            _pt("long", 0, 10),  # impact 10
            _pt("mid", 10, 14),  # impact 4
            _pt("short", 14, 15),  # impact 1 → dropped
        ]
        plan = plan_batches(pts, max_points=2, max_calls=1)
        assert plan["n_calls"] == 1
        kept = [c["key"] for c in plan["batches"][0]]
        assert kept == ["long", "mid"]  # time order among kept
        assert [c["key"] for c in plan["dropped"]] == ["short"]

    def test_summary_flags_drops(self):
        pts = [_pt("long", 0, 10), _pt("short", 10, 11)]
        plan = plan_batches(pts, max_points=1, max_calls=1)
        line = summarize(plan)
        assert "DROPPED" in line and "fallback" in line

    def test_fallback_carried_on_every_cluster(self):
        plan = plan_batches([_pt("k", 0, 2)])
        assert plan["batches"][0][0]["fallback"] == {"action": "crop"}
