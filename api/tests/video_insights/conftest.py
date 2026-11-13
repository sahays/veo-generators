"""Shared doubles for the engagement processor tests: storage, Firestore and Gemini."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest

# `deps` first: importing a Gemini mixin module on its own trips the existing
# helpers -> deps -> gemini_service import cycle.
import deps
from gemini_insights import InsightResponse
from models import EngagementRecord, SceneAnalysisRecord, UsageMetrics
from models_insights import EngagementSignalSpec

BUCKET = "test-bucket"
TIMELINE_URI = f"gs://{BUCKET}/scene_analysis/sa-1/timeline.json"
_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "engagement_signals"
    / "timeline_small.json"
)
Outcome = Callable[[dict[str, Any]], Any]


class MemoryStorage:
    """In-memory bucket that counts downloads and can refuse an upload once."""

    bucket_name = BUCKET

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.downloads: list[str] = []
        self.fail_upload_of: Optional[str] = None

    def _path(self, gcs_uri: str) -> str:
        return gcs_uri.removeprefix(f"gs://{BUCKET}/")

    def upload_bytes(self, data: bytes, path: str, content_type: str = "") -> str:
        if self.fail_upload_of and path.endswith(self.fail_upload_of):
            self.fail_upload_of = None
            raise ConnectionError("bucket unavailable")
        self.objects[path] = data
        return f"gs://{BUCKET}/{path}"

    def blob_exists(self, gcs_uri: str) -> bool:
        return self._path(gcs_uri) in self.objects

    def download_bytes(self, gcs_uri: str) -> bytes:
        self.downloads.append(self._path(gcs_uri))
        return self.objects[self._path(gcs_uri)]

    def get_file_size(self, gcs_uri: str) -> int:
        return len(self.objects.get(self._path(gcs_uri), b""))

    def json(self, path: str) -> dict[str, Any]:
        return json.loads(self.objects[path])


class MemoryStore:
    """Firestore double holding real records; counts reads and records writes."""

    def __init__(self) -> None:
        self.engagements: dict[str, EngagementRecord] = {}
        self.analyses: dict[str, SceneAnalysisRecord] = {}
        self.analysis_list_reads = 0
        self.analysis_gets = 0
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def get_engagements(self, include_archived: bool = False) -> list:
        records = self.engagements.values()
        return [r for r in records if include_archived or not r.archived]

    def get_scene_analyses(self, include_archived: bool = False) -> list:
        self.analysis_list_reads += 1
        records = self.analyses.values()
        return [r for r in records if include_archived or not r.archived]

    def get_scene_analysis(self, record_id: str) -> Optional[SceneAnalysisRecord]:
        self.analysis_gets += 1
        return self.analyses.get(record_id)

    def update_engagement(self, record_id: str, updates: dict[str, Any]) -> None:
        self.writes.append((record_id, dict(updates)))
        stored = {**self.engagements[record_id].model_dump(), **updates}
        self.engagements[record_id] = EngagementRecord(**stored)


def prompt_data(prompt: str) -> dict[str, Any]:
    """The JSON inside a prompt's delimited data block."""
    body = prompt.split("<<<ANALYSIS_DATA\n", 1)[1]
    return json.loads(body.rsplit("\nANALYSIS_DATA>>>", 1)[0])


def _usage() -> UsageMetrics:
    return UsageMetrics(
        input_tokens=1000, output_tokens=100, cost_usd=0.01, model_name="m"
    )


def answer(data: dict[str, Any], finish: str = "STOP") -> InsightResponse:
    return InsightResponse(data=data, usage=_usage(), finish_reason=finish)


def explain_answer(data: dict[str, Any]) -> InsightResponse:
    """Prose for every moment, plus figures and an id the server must ignore."""
    items = [
        {
            "id": moment["id"],
            "title": f"Title {moment['id']}",
            "explanation": f"Because of {moment['id']}.",
            "drivers": ["Asha", "the reveal"],
            "delta_pct": 999.0,
            "value": -1.0,
        }
        for moment in data["moments"]
    ]
    items.append({"id": "peak-99", "title": "Invented", "explanation": "x"})
    return answer({"explanations": items})


def recommend_answer(data: dict[str, Any]) -> InsightResponse:
    """Advice citing supplied keys, plus a key and a segment that do not exist."""

    def action(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": f"About {entry['name']}",
            "rationale": "It coincides.",
            "expected_lift": "medium",
            "key": entry["key"],
            "delta_pct": 999.0,
        }

    invented = action({"name": "nobody", "key": "character:nobody"})
    fixes = [
        {
            "segment_id": s["segment_id"],
            "what_happened": "w",
            "why_low": "y",
            "fix": "f",
        }
        for s in data["low_segments"][:1]
    ]
    fixes.append(
        {"segment_id": "seg-99", "what_happened": "w", "why_low": "y", "fix": "f"}
    )
    return answer(
        {
            "headline": "The headline.",
            "do_more": [action(e) for e in data["top_influence"][:2]],
            "do_less": [action(e) for e in data["bottom_influence"][:1]] + [invented],
            "segment_fixes": fixes,
        }
    )


class ScriptedAI:
    """Answers `generate_insight_json`; `outcomes` overrides a call by its kind."""

    def __init__(self) -> None:
        self.outcomes: dict[str, Outcome] = {
            "explain": explain_answer,
            "recommend": recommend_answer,
        }
        self.calls: list[SimpleNamespace] = []

    async def generate_insight_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Any:
        kind = "explain" if "explanations" in schema["properties"] else "recommend"
        call = SimpleNamespace(
            kind=kind, prompt=prompt, schema=schema, model_id=model_id, region=region
        )
        self.calls.append(call)
        result = self.outcomes[kind](prompt_data(prompt))
        if isinstance(result, Exception):
            raise result
        return result

    def kinds(self) -> list[str]:
        return [call.kind for call in self.calls]


def _add_analysis(
    env: SimpleNamespace, record_id: str = "sa-1", **fields: Any
) -> SceneAnalysisRecord:
    record = SceneAnalysisRecord(
        id=record_id,
        **{
            "source_id": "up-1",
            "video_gcs_uri": f"gs://{BUCKET}/uploads/cook.mp4",
            "status": "completed",
            "timeline_gcs_uri": TIMELINE_URI,
            **fields,
        },
    )
    env.store.analyses[record_id] = record
    return record


def _add_job(
    env: SimpleNamespace, record_id: str = "en-1", **fields: Any
) -> EngagementRecord:
    signal = EngagementSignalSpec(kind="template", template_id="jumpy")
    record = EngagementRecord(
        id=record_id,
        **{
            "scene_analysis_id": "sa-1",
            "source_id": "up-1",
            "video_gcs_uri": f"gs://{BUCKET}/uploads/cook.mp4",
            "signal": signal,
            "model_id": "custom-model",
            "region": "us-central1",
            **fields,
        },
    )
    env.store.engagements[record_id] = record
    return record


@pytest.fixture
def engagement_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """In-memory services around a 120 s timeline stored for analysis `sa-1`.

    `add_analysis` / `add_job` seed records; `job(id)` reads a record back with
    every write applied; `timeline` is the stored timeline document.
    """
    storage, store, ai = MemoryStorage(), MemoryStore(), ScriptedAI()
    timeline = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    storage.objects["scene_analysis/sa-1/timeline.json"] = json.dumps(timeline).encode()
    monkeypatch.setattr(deps, "storage_svc", storage)
    monkeypatch.setattr(deps, "firestore_svc", store)
    monkeypatch.setattr(deps, "ai_svc", ai)
    env = SimpleNamespace(
        storage=storage,
        store=store,
        ai=ai,
        timeline=timeline,
        timeline_uri=TIMELINE_URI,
    )
    env.add_analysis = lambda *args, **fields: _add_analysis(env, *args, **fields)
    env.add_job = lambda *args, **fields: _add_job(env, *args, **fields)
    env.job = lambda record_id="en-1": store.engagements[record_id]
    env.answer = answer
    env.prompt_data = prompt_data
    return env
