#!/usr/bin/env python3
"""Honest Codebase Index Checker & Synchronizer.

Verifies that CODEBASE_INDEX.json and CODEBASE_INDEX.md match the live repository
filesystem and AST/symbol signatures in O(N) time using hash-map lookups.
Detects added/unindexed files, deleted/moved phantom files, and stale symbol or
statement-count metadata.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_JSON_PATH = REPO_ROOT / "CODEBASE_INDEX.json"
INDEX_MD_PATH = REPO_ROOT / "CODEBASE_INDEX.md"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_codebase_index.py"


@dataclass(frozen=True)
class IndexDrift:
    category: str
    path: str
    detail: str


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "generate_codebase_index", GENERATOR_PATH
    )
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load generator at {GENERATOR_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_codebase_index"] = mod
    spec.loader.exec_module(mod)
    return mod


def _compare_file_entries(
    live_map: dict[str, dict[str, Any]],
    disk_map: dict[str, dict[str, Any]],
) -> list[IndexDrift]:
    drifts: list[IndexDrift] = []
    live_paths = set(live_map.keys())
    disk_paths = set(disk_map.keys())

    for added in sorted(live_paths - disk_paths):
        drifts.append(
            IndexDrift(
                "UNINDEXED_FILE",
                added,
                "File exists on disk but is missing from CODEBASE_INDEX.json",
            )
        )
    for removed in sorted(disk_paths - live_paths):
        drifts.append(
            IndexDrift(
                "PHANTOM_FILE",
                removed,
                "File is in CODEBASE_INDEX.json but was moved or deleted from disk",
            )
        )

    tracked_keys = ("tier", "non_comment_lines", "classes", "functions", "endpoints")
    for common in sorted(live_paths & disk_paths):
        live_entry = live_map[common]
        disk_entry = disk_map[common]
        mismatch = [k for k in tracked_keys if live_entry.get(k) != disk_entry.get(k)]
        if mismatch:
            drifts.append(
                IndexDrift(
                    "STALE_METADATA",
                    common,
                    f"Out-of-date index fields: {', '.join(mismatch)}",
                )
            )
    return drifts


def _build_live_payload(gen: Any) -> dict[str, Any]:
    entries = gen._collect_all_entries()
    return dict(gen._build_payload(entries))


def check_index_honesty(live_payload: dict[str, Any] | None = None) -> list[IndexDrift]:
    """Compare live codebase state against CODEBASE_INDEX.json in O(N) time."""
    gen = _load_generator()
    payload = live_payload if live_payload is not None else _build_live_payload(gen)
    if not INDEX_JSON_PATH.exists():
        return [
            IndexDrift(
                "MISSING_INDEX",
                "CODEBASE_INDEX.json",
                "CODEBASE_INDEX.json does not exist",
            )
        ]
    if not INDEX_MD_PATH.exists():
        return [
            IndexDrift(
                "MISSING_INDEX", "CODEBASE_INDEX.md", "CODEBASE_INDEX.md does not exist"
            )
        ]

    try:
        disk_payload = json.loads(INDEX_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return [
            IndexDrift("CORRUPT_INDEX", "CODEBASE_INDEX.json", f"Invalid JSON: {exc}")
        ]

    live_map = {entry["path"]: entry for entry in payload.get("files", [])}
    disk_map = {entry["path"]: entry for entry in disk_payload.get("files", [])}
    return _compare_file_entries(live_map, disk_map)


def sync_codebase_index() -> tuple[list[IndexDrift], dict[str, Any]]:
    """Detect any drift and write fresh CODEBASE_INDEX.json and CODEBASE_INDEX.md."""
    gen = _load_generator()
    live_payload = _build_live_payload(gen)
    drifts = check_index_honesty(live_payload)
    INDEX_JSON_PATH.write_text(
        json.dumps(live_payload, indent=2) + "\n", encoding="utf-8"
    )
    INDEX_MD_PATH.write_text(gen._render_markdown(live_payload), encoding="utf-8")
    return drifts, live_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify or synchronize CODEBASE_INDEX honesty."
    )
    parser.add_argument(
        "--sync", action="store_true", help="Synchronize index files before checking."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail with exit code 1 if index has any drift.",
    )
    args = parser.parse_args(argv)

    if args.sync:
        drifts, payload = sync_codebase_index()
        print(
            f"✅ Synchronized CODEBASE_INDEX ({payload['total_files']} files, "
            f"{len(drifts)} drift items resolved)."
        )
        if not args.check:
            return 0

    drifts = check_index_honesty()
    if drifts:
        print(f"❌ CODEBASE_INDEX honesty check failed with {len(drifts)} issue(s):")
        for d in drifts[:25]:
            print(f"   - [{d.category}] {d.path}: {d.detail}")
        print(
            "   💡 Run `python3 scripts/check_codebase_index.py --sync` to update the index."
        )
        return 1

    print("✅ CODEBASE_INDEX is 100% honest and synchronized with the working tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
