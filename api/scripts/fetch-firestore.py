#!/usr/bin/env python3
"""Fetch a Firestore document (or list a collection) and output it as JSON.

Reusable debugging helper — pull a reframe record's stored plan/eval, an upload,
a production, etc., without the API or auth middleware in the way.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from typing import Any

logger = logging.getLogger("fetch_firestore")


def _emit(msg: str, where: str = "fetch_firestore") -> None:
    logger.info(
        msg,
        extra={
            "who": "fetch_firestore",
            "where": where,
            "what": msg[:120],
            "why": "Inspect Firestore documents",
            "how": "cli",
        },
    )


def _credentials(project: str) -> Any:
    """ADC if available, else a bearer credential from the active gcloud account."""
    _ = project
    try:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default()
        creds.refresh(Request())
        return creds
    except Exception as err:  # noqa: BLE001
        _emit(
            f"[fetch_firestore] ADC unusable ({err}); using gcloud token",
            "_credentials",
        )
        cmd = ["gcloud", "auth", "print-access-token"]
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        from google.oauth2.credentials import Credentials

        return Credentials(token=proc.stdout.strip())


def _default_collection() -> str:
    prefix = os.getenv("SERVICE_NAME", "veo-generators").replace("-", "_")
    return f"{prefix}_reframes"


def _parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
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
    return ap, ap.parse_args()


def main() -> int:
    ap, args = _parse_args()
    from google.cloud import firestore

    creds = _credentials(args.project)
    db = firestore.Client(
        project=args.project, credentials=creds, database=args.database
    )
    col = db.collection(args.collection)

    if args.list:
        rows = [
            {"id": snap.id, "status": (snap.to_dict() or {}).get("status")}
            for snap in col.limit(args.limit).stream()
        ]
        _emit(json.dumps(rows, indent=1, default=str), "main")
        return 0

    if not args.doc_id:
        sys.exit("doc_id is required unless --list is given")

    snap = col.document(args.doc_id).get()
    if not snap.exists:
        _emit(f"NOT FOUND: {args.collection}/{args.doc_id}", "main")
        return 1
    data = snap.to_dict() or {}
    if args.fields:
        keep = {f.strip() for f in args.fields.split(",")}
        data = {k: v for k, v in data.items() if k in keep}
    _emit(json.dumps(data, indent=1, default=str), "main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
