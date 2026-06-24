#!/usr/bin/env python3
"""Fetch a Firestore document (or list a collection) and print it as JSON.

Reusable debugging helper — pull a reframe record's stored plan/eval, an upload,
a production, etc., without the API or auth middleware in the way.

Auth: tries ADC (`google.auth.default()` — works on Cloud Run / a configured
env), and falls back to the ACTIVE gcloud account's access token
(`gcloud auth print-access-token`) so it works locally with a service account
that ADC can't refresh non-interactively.

Examples:
  # Whole document
  python scripts/fetch_firestore.py rf-vlsygfxe

  # A reframe record, only the fields you care about
  python scripts/fetch_firestore.py rf-vlsygfxe \
      --fields segment_plan,reframe_summary,eval_report,speaker_segments

  # Different collection / project
  python scripts/fetch_firestore.py abc123 --collection veo_generators_uploads

  # List N docs (ids + status) instead of one
  python scripts/fetch_firestore.py --list --limit 10

Collection defaults to `{SERVICE_NAME}_reframes` (SERVICE_NAME env or
"veo-generators"). Output is JSON on stdout; pipe to jq for slicing.
"""

import argparse
import json
import os
import subprocess
import sys


def _credentials(project: str):
    """ADC if available, else a bearer credential from the active gcloud account."""
    try:
        import google.auth

        creds, _ = google.auth.default()
        # Force a refresh so a broken ADC fails HERE (fast) not on first RPC (hang).
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        return creds
    except Exception as e:  # noqa: BLE001
        print(
            f"[fetch_firestore] ADC unusable ({e}); using gcloud token", file=sys.stderr
        )
        token = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        from google.oauth2.credentials import Credentials

        return Credentials(token=token)


def _default_collection() -> str:
    prefix = os.getenv("SERVICE_NAME", "veo-generators").replace("-", "_")
    return f"{prefix}_reframes"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("doc_id", nargs="?", help="document id (omit with --list)")
    ap.add_argument("--collection", default=_default_collection())
    ap.add_argument(
        "--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "random-poc-479104")
    )
    ap.add_argument("--database", default=os.getenv("FIRESTORE_DATABASE", "(default)"))
    ap.add_argument(
        "--fields", help="comma-separated top-level fields to keep (default: all)"
    )
    ap.add_argument("--list", action="store_true", help="list docs instead of one")
    ap.add_argument("--limit", type=int, default=20, help="--list page size")
    args = ap.parse_args()

    from google.cloud import firestore

    creds = _credentials(args.project)
    db = firestore.Client(
        project=args.project, credentials=creds, database=args.database
    )
    col = db.collection(args.collection)

    if args.list:
        rows = []
        for snap in col.limit(args.limit).stream():
            d = snap.to_dict() or {}
            rows.append({"id": snap.id, "status": d.get("status")})
        print(json.dumps(rows, indent=1, default=str))
        return 0

    if not args.doc_id:
        ap.error("doc_id is required unless --list is given")

    snap = col.document(args.doc_id).get()
    if not snap.exists:
        print(f"NOT FOUND: {args.collection}/{args.doc_id}", file=sys.stderr)
        return 1
    data = snap.to_dict() or {}
    if args.fields:
        keep = {f.strip() for f in args.fields.split(",")}
        data = {k: v for k, v in data.items() if k in keep}
    print(json.dumps(data, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
