"""EngagementProcessor stages: template and BARC reports, resume, model failures."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace
from typing import Any

import pytest

from insight_jobs.engagement_processor import EngagementProcessor
from models_insights import EngagementSignalSpec

REPORT = "engagement/en-1/report.json"
REPORT_KEYS = [
    "schema_version",
    "duration_sec",
    "signal",
    "metrics",
    "smoothed",
    "stats",
    "extrema",
    "segments",
    "influence",
    "recommendations",
    "kpis",
]
CSV_PATH = "uploads/ratings.csv"


def _barc_csv() -> bytes:
    """24 samples, 5 s apart: `TVR` swings, `Reach` rises; one `Reach` cell is unreadable."""
    rows = ["Time,TVR,Reach"]
    for step in range(24):
        elapsed = step * 5
        reach = "n/a" if step == 7 else str(200 + 10 * step)
        clock = f"00:{elapsed // 60:02d}:{elapsed % 60:02d}"
        rows.append(f"{clock},{5.0 + 2.5 * math.sin(step / 3.0):.2f},{reach}")
    return "\n".join(rows).encode()


def _barc_job(env: SimpleNamespace, **signal: Any) -> Any:
    env.storage.objects[CSV_PATH] = _barc_csv()
    spec = EngagementSignalSpec(
        kind="barc",
        upload_id="up-csv",
        csv_gcs_uri=f"gs://test-bucket/{CSV_PATH}",
        csv_filename="ratings.csv",
        **signal,
    )
    return env.add_job("en-1", signal=spec)


def _run(env: SimpleNamespace, record_id: str = "en-1") -> dict[str, Any]:
    """Process the stored job and return its `report.json`."""
    EngagementProcessor().process(env.job(record_id))
    return env.storage.json(f"engagement/{record_id}/report.json")


# ── Template signal ──────────────────────────────────────────────────


def test_template_job_writes_a_full_report_and_record_summaries(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1")
    report = _run(env)
    assert list(report) == REPORT_KEYS
    assert report["signal"] == {
        "kind": "template",
        "template_id": "jumpy",
        "label": "Jumpy",
        "simulated": True,
        "primary_metric": "Engagement index",
        "unit": "index",
        "offset_sec": 0.0,
        "point_count": 120,
        "interval_sec": 1.0,
    }
    job = env.job()
    assert (job.status, job.progress_pct, job.stage, job.stage_detail) == (
        "completed",
        100,
        "",
        "",
    )
    assert job.report_gcs_uri == f"gs://test-bucket/{REPORT}"
    assert (job.duration_sec, job.headline) == (120.0, "The headline.")
    assert job.kpis == report["kpis"] and job.kpis["peak"]["value"] > job.kpis["avg"]
    assert job.completedAt is not None
    # Two model calls, each with the record's model and region.
    assert env.ai.kinds() == ["explain", "recommend"]
    assert {(c.model_id, c.region) for c in env.ai.calls} == {
        ("custom-model", "us-central1")
    }
    assert (job.usage.input_tokens, job.usage.output_tokens) == (2000, 200)
    assert job.usage.cost_usd == pytest.approx(0.02)


def test_model_prose_is_bound_by_id_and_never_supplies_a_number(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1")
    report = _run(env)
    extrema = report["extrema"]
    assert len(extrema) >= 3 and "peak-99" not in {e["id"] for e in extrema}
    for extremum in extrema:
        assert extremum["title"] == f"Title {extremum['id']}"
        assert extremum["explanation"] == f"Because of {extremum['id']}."
        assert extremum["drivers"] == ["Asha", "the reveal"]
        # The model answered delta_pct=999 and value=-1 for every moment.
        assert extremum["delta_pct"] != 999.0 and extremum["value"] >= 0
    advice = report["recommendations"]
    influence = {entry["key"]: entry for entry in report["influence"]}
    cited = [item["evidence"] for item in advice["do_more"] + advice["do_less"]]
    assert len(advice["do_more"]) == 2 and len(advice["do_less"]) == 1
    for evidence in cited:
        entry = influence[evidence["key"]]
        assert evidence["delta_pct"] == entry["delta_pct"] != 999.0
        assert evidence["coverage_sec"] == entry["coverage_sec"]
    assert all(e["delta_pct"] > 0 for e in cited[:2]) and cited[2]["delta_pct"] < 0
    (fix,) = advice["segment_fixes"]
    segment = next(s for s in env.timeline["segments"] if s["id"] == fix["segment_id"])
    assert (fix["start_sec"], fix["end_sec"]) == (
        segment["start_sec"],
        segment["end_sec"],
    )


def test_the_model_is_given_only_ids_the_report_contains(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1")
    report = _run(env)
    explain, recommend = (env.prompt_data(call.prompt) for call in env.ai.calls)
    assert [m["id"] for m in explain["moments"]] == [e["id"] for e in report["extrema"]]
    assert explain["signal"]["simulated"] is True
    assert explain["video"]["content_title"] == "Cook-off"
    assert all(m["context"]["segments"] for m in explain["moments"])
    keys = {entry["key"] for entry in report["influence"]}
    offered = recommend["top_influence"] + recommend["bottom_influence"]
    assert offered and {entry["key"] for entry in offered} <= keys
    assert env.ai.calls[0].schema["required"] == ["explanations"]
    assert "segment_fixes" in env.ai.calls[1].schema["required"]


def test_a_template_report_is_reproducible_for_a_record_id(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1")
    first = _run(env)
    # A fresh job with the same id starts from an empty bucket prefix.
    for path in [p for p in env.storage.objects if p.startswith("engagement/")]:
        del env.storage.objects[path]
    env.add_job("en-1")
    assert _run(env) == first
    env.add_job("en-2")
    other = _run(env, "en-2")
    assert other["metrics"][0]["points"] != first["metrics"][0]["points"]
    assert other["signal"] == first["signal"]


# ── BARC signal ──────────────────────────────────────────────────────


def test_barc_job_parses_the_csv_with_the_records_overrides(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    _barc_job(env, metric="Reach", offset_sec=10.0)
    report = _run(env)
    signal = report["signal"]
    assert (signal["kind"], signal["simulated"], signal["template_id"]) == (
        "barc",
        False,
        None,
    )
    assert (signal["label"], signal["primary_metric"]) == ("ratings.csv", "Reach")
    assert (signal["offset_sec"], signal["interval_sec"]) == (10.0, 5.0)
    primary, secondary = report["metrics"]
    assert (primary["label"], primary["primary"]) == ("Reach", True)
    assert (secondary["label"], secondary["primary"]) == ("TVR", False)
    # The first CSV row (00:00:00) lands at the 10 s offset. Rows that land at or
    # after the end of the 120 s video are discarded, and the n/a cell is skipped.
    assert primary["points"][0] == [10.0, 200.0]
    assert primary["points"][-1] == [115.0, 410.0]
    assert (len(primary["points"]), len(secondary["points"])) == (21, 22)
    assert report["kpis"]["peak"] == {"time_sec": 115.0, "value": 410.0}
    job = env.job()
    assert job.status == "completed"
    # Parser warnings are the user's only hint that rows were dropped.
    assert "Skipped 1 row(s)" in job.stage_detail
    assert env.prompt_data(env.ai.calls[0].prompt)["signal"]["simulated"] is False


# ── Retry ────────────────────────────────────────────────────────────


def test_a_retried_job_reuses_checkpoints_instead_of_paying_again(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    _barc_job(env)
    env.storage.fail_upload_of = "report.json"
    with pytest.raises(ConnectionError):
        _run(env)
    assert env.ai.kinds() == ["explain", "recommend"]
    assert REPORT not in env.storage.objects and env.job().status == "processing"
    first_csv_reads = env.storage.downloads.count(CSV_PATH)
    report = _run(env)
    # No further model call and no second CSV download or parse.
    assert env.ai.kinds() == ["explain", "recommend"]
    assert (first_csv_reads, env.storage.downloads.count(CSV_PATH)) == (1, 1)
    assert report["extrema"][0]["title"] == f"Title {report['extrema'][0]['id']}"
    assert report["recommendations"]["headline"] == "The headline."
    job = env.job()
    assert job.status == "completed"
    # The record still shows what the report cost, although this run was free.
    assert (job.usage.input_tokens, job.usage.output_tokens) == (2000, 200)


def test_checkpoints_made_for_other_inputs_are_not_reused(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1", signal=EngagementSignalSpec(kind="template", template_id="low"))
    low = _run(env)
    # Same record id, different template: every checkpoint on disk is stale.
    env.add_job("en-1")
    jumpy = _run(env)
    assert jumpy["signal"]["template_id"] == "jumpy"
    assert jumpy["metrics"][0]["points"] != low["metrics"][0]["points"]
    assert env.ai.kinds() == ["explain", "recommend"] * 2
    assert {e["id"] for e in jumpy["extrema"] if e["title"]} == {
        e["id"] for e in jumpy["extrema"]
    }


# ── Model failures are not job failures ──────────────────────────────


def _raises(_data: dict[str, Any]) -> Exception:
    return TimeoutError("deadline exceeded for projects/secret-project")


@pytest.mark.parametrize("failure", ["raises", "truncated", "empty", "wrong_shape"])
@pytest.mark.parametrize("stage", ["explain", "recommend"])
def test_a_failed_model_call_keeps_the_numbers_and_notes_the_gap(
    engagement_env: SimpleNamespace, stage: str, failure: str
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1")
    partial = {"explanations": [{"id": "peak-1"}], "headline": "cut off mid-"}
    outcomes = {
        "raises": _raises,
        "truncated": lambda data: env.answer(partial, finish="MAX_TOKENS"),
        "empty": lambda data: env.answer({}),
        "wrong_shape": lambda data: env.answer({"explanations": "none", "do_more": 3}),
    }
    env.ai.outcomes[stage] = outcomes[failure]
    report = _run(env)
    job = env.job()
    assert (job.status, job.progress_pct, job.error_message) == ("completed", 100, None)
    assert env.ai.kinds() == ["explain", "recommend"]
    explained = [e for e in report["extrema"] if e["title"] or e["explanation"]]
    advice = report["recommendations"]
    if stage == "explain":
        assert job.stage_detail == "Explanations could not be generated"
        assert explained == [] and advice["headline"] == "The headline."
    else:
        assert job.stage_detail == "Recommendations could not be generated"
        assert len(explained) == len(report["extrema"])
        assert advice == {
            "headline": "",
            "do_more": [],
            "do_less": [],
            "segment_fixes": [],
        }
        assert job.headline == ""
    # The deterministic part of the report is complete either way.
    assert len(report["extrema"]) >= 3 and report["influence"] and report["segments"]
    assert job.kpis["avg"] == report["stats"]["avg"] > 0
    assert "secret-project" not in job.stage_detail
    # A call that produced nothing usable is not checkpointed, but is still paid for.
    assert f"engagement/en-1/{stage}.json" not in env.storage.objects
    paid_calls = 1 if failure == "raises" else 2
    assert job.usage.input_tokens == 1000 * paid_calls


def test_no_model_call_is_made_when_there_is_nothing_to_describe(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    bare = {"schema_version": "video-timeline-v1", "duration_sec": 1.0}
    env.storage.objects["scene_analysis/sa-1/timeline.json"] = json.dumps(bare).encode()
    env.add_analysis("sa-1")
    env.add_job("en-1", signal=EngagementSignalSpec(kind="template", template_id="low"))
    report = _run(env)
    assert report["extrema"] == [] and report["influence"] == []
    assert env.ai.calls == []
    job = env.job()
    assert (job.status, job.usage.input_tokens) == ("completed", 0)
    assert job.stage_detail == "Too little timeline detail for recommendations"
