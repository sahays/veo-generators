#!/usr/bin/env python3
"""Build, verify, and rebaseline reframe replay fixtures.

A fixture bundles one production job's raw pipeline inputs (the
``detections.json.gz`` the worker dumps to GCS) with its stored plan/eval from
Firestore, committed under ``api/tests/fixtures/reframe/`` so
``test_reframe_regression.py`` can replay it deterministically in CI.
"""

import argparse
import gzip
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = API_DIR / "tests" / "fixtures" / "reframe"
BASELINES = FIXTURE_DIR / "baselines.json"
sys.path.insert(0, str(API_DIR))

SERVICE = os.getenv("SERVICE_NAME", "veo-generators")
BUCKET = os.getenv("GCS_BUCKET", "superexam-uploads")
logger = logging.getLogger("build_reframe_fixture")


def _log(msg: str, where: str = "build_reframe_fixture") -> None:
    logger.info(
        msg,
        extra={
            "who": "build_reframe_fixture",
            "where": where,
            "what": msg[:120],
            "why": "Reframe fixture management",
            "how": "cli",
        },
    )


def _credentials() -> Any:
    """ADC if available, else a bearer credential from the active gcloud account."""
    try:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default()
        creds.refresh(Request())
        return creds
    except Exception as e:  # noqa: BLE001
        _log(f"[fixture] ADC unusable ({e}); using gcloud token", "_credentials")
        token = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        from google.oauth2.credentials import Credentials

        return Credentials(token=token)


def _fetch_gcs(job_id: str) -> dict:
    from google.cloud import storage

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    client = storage.Client(project=project, credentials=_credentials())
    blob = client.bucket(BUCKET).blob(f"reframes/{job_id}/detections.json.gz")
    if not blob.exists():
        sys.exit(
            f"ERROR: gs://{BUCKET}/reframes/{job_id}/detections.json.gz not found — "
            "the job predates the fixture dump; re-run it (diagnostic mode works too)."
        )
    return json.loads(gzip.decompress(blob.download_as_bytes()))


def _fetch_firestore(job_id: str) -> dict:
    from google.cloud import firestore

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    client = firestore.Client(project=project, credentials=_credentials())
    doc = client.collection(f"{SERVICE}_reframes").document(job_id).get()
    if not doc.exists:
        sys.exit(f"ERROR: no Firestore record {job_id} in {SERVICE}_reframes")
    d = doc.to_dict()
    return {
        "stored_plan": d.get("segment_plan"),
        "stored_summary": d.get("reframe_summary"),
        "stored_eval": d.get("eval_report"),
    }


def build(job_id: str) -> Path:
    fixture = _fetch_gcs(job_id)
    fixture.update(_fetch_firestore(job_id))
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{job_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(fixture, f, default=float)
    _log(f"wrote {path} ({path.stat().st_size // 1024} KiB)", "build")
    return path


def _load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def rebaseline() -> None:
    from reframe_replay import plan_metrics, replay

    baselines = {}
    for path in sorted(FIXTURE_DIR.glob("*.json.gz")):
        job = path.name.split(".")[0]
        result = replay(_load(path))
        baselines[job] = plan_metrics(result["segments"], result["report"])
        _log(f"{job}: {json.dumps(baselines[job])}", "rebaseline")
    if not baselines:
        sys.exit("no fixtures found — build some first")
    BASELINES.write_text(json.dumps(baselines, indent=2, sort_keys=True) + "\n")
    _log(f"wrote {BASELINES}", "rebaseline")


def verify() -> None:
    """Phase-0 gate: replay must reproduce each stored production plan."""
    from reframe_replay import compact_plan, replay

    failures = 0
    for path in sorted(FIXTURE_DIR.glob("*.json.gz")):
        job = path.name.split(".")[0]
        fixture = _load(path)
        stored = fixture.get("stored_plan")
        if not stored:
            _log(f"{job}: SKIP (no stored plan in fixture)", "verify")
            continue
        replayed = compact_plan(replay(fixture)["segments"])
        stored_cmp = [
            {k: s.get(k) for k in ("start", "end", "layout", "inner_ar", "reason")}
            for s in stored
        ]
        if replayed == stored_cmp:
            _log(f"{job}: OK ({len(replayed)} segments byte-equal)", "verify")
            continue
        failures += 1
        _log(
            f"{job}: MISMATCH ({len(replayed)} vs {len(stored_cmp)} segments)", "verify"
        )
        for i, (a, b) in enumerate(zip(replayed, stored_cmp)):
            if a != b:
                _log(f"  seg {i}: replay={a} stored={b}", "verify")
    sys.exit(1 if failures else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job_ids", nargs="*", help="reframe job id(s) to fetch")
    ap.add_argument("--rebaseline", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if args.job_ids:
        for job_id in args.job_ids:
            build(job_id)
    if args.rebaseline:
        rebaseline()
    if args.verify:
        verify()
    if not (args.job_ids or args.rebaseline or args.verify):
        ap.print_help()


if __name__ == "__main__":
    main()
