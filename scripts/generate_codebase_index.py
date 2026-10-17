#!/usr/bin/env python3
"""Fast AST/regex codebase index generator for O(1) architectural discovery.

Scans `api/`, `workers/`, `agents_service/`, `productions_service/`, `scripts/`,
and `frontend/src/`, emitting:
- `CODEBASE_INDEX.json` (structured index of directories, domain packages, and files)
- `CODEBASE_INDEX.md` (concise, navigable Markdown reference at the repository root)
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from checkers.arch_tiers import (  # noqa: E402
    BACKEND_TIER_NAMES,
    FRONTEND_TIER_NAMES,
    classify_backend_module,
    classify_frontend_module,
)
from checkers.models import FRONTEND_SRC_DIR, PYTHON_SCAN_DIRS, REPO_ROOT  # noqa: E402
from checkers.size_and_types import count_py_non_comment_lines  # noqa: E402

_HTTP_METHODS: frozenset[str] = frozenset({"get", "post", "put", "patch", "delete", "websocket"})
_TS_COMMENT_RE: re.Pattern[str] = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_TS_EXPORT_RE: re.Pattern[str] = re.compile(
    r"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|interface|type|enum)\s+([A-Za-z0-9_]+)"
)


class FileIndexEntry(TypedDict):
    """Metadata entry for a single Python or TypeScript source file."""

    path: str
    language: str
    domain_package: str
    tier: str
    non_comment_lines: int
    classes: list[str]
    functions: list[str]
    endpoints: list[str]


class CodebaseIndexPayload(TypedDict):
    """Root JSON structure written to `CODEBASE_INDEX.json`."""

    total_files: int
    domain_packages: dict[str, int]
    directory_tree: list[str]
    files: list[FileIndexEntry]


def _resolve_py_tier_label(rel_path: str) -> str:
    """Return human-readable architectural tier label for a Python file."""
    if "/tests/" in f"/{rel_path}" or Path(rel_path).name.startswith("test_"):
        return "Test Suite"
    if rel_path.startswith("scripts/"):
        return "Tier 5 (Entrypoints, Scripts & Workers)"
    tier = classify_backend_module(rel_path)
    return BACKEND_TIER_NAMES.get(tier, "Support / Package") if tier else "Support / Package"


def _resolve_ts_tier_label(rel_repo: str) -> str:
    """Return human-readable architectural tier label for a TypeScript file."""
    rel_src = rel_repo.removeprefix("frontend/src/")
    tier, domain = classify_frontend_module(rel_src)
    base = FRONTEND_TIER_NAMES.get(tier, f"Tier {tier}")
    return f"{base} [{domain}]" if domain else base


def _extract_py_route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract FastAPI route decorators (`GET /path`) attached to a function node."""
    routes: list[str] = []
    for dec in node.decorator_list:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
            continue
        method = dec.func.attr.lower()
        if method not in _HTTP_METHODS:
            continue
        route_path = "/"
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            route_path = dec.args[0].value
        routes.append(f"{method.upper()} {route_path}")
    return routes


def _parse_py_symbols(source: str, rel_path: str) -> tuple[list[str], list[str], list[str]]:
    """Return `(classes, functions, endpoints)` from a Python module's top-level AST."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return [], [], []
    classes: list[str] = []
    functions: list[str] = []
    endpoints: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(node.name)
            endpoints.extend(_extract_py_route_decorators(node))
    return classes, functions, endpoints


def _index_py_file(path: Path) -> FileIndexEntry:
    """Build a `FileIndexEntry` for a single Python file."""
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    source = path.read_text(encoding="utf-8")
    classes, functions, endpoints = _parse_py_symbols(source, rel)
    parts = rel.split("/")
    domain_pkg = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
    return {
        "path": rel,
        "language": "python",
        "domain_package": domain_pkg,
        "tier": _resolve_py_tier_label(rel),
        "non_comment_lines": count_py_non_comment_lines(source),
        "classes": classes,
        "functions": functions,
        "endpoints": endpoints,
    }


def _index_ts_file(path: Path) -> FileIndexEntry:
    """Build a `FileIndexEntry` for a single TypeScript/TSX file."""
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    source = path.read_text(encoding="utf-8")
    clean = _TS_COMMENT_RE.sub("", source)
    non_comment = sum(1 for ln in clean.splitlines() if ln.strip())
    exports = list(dict.fromkeys(m.group(1) for m in _TS_EXPORT_RE.finditer(clean)))
    parts = rel.split("/")
    domain_pkg = "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:2])
    return {
        "path": rel,
        "language": "typescript",
        "domain_package": domain_pkg,
        "tier": _resolve_ts_tier_label(rel),
        "non_comment_lines": non_comment,
        "classes": [],
        "functions": exports,
        "endpoints": [],
    }


def _collect_all_entries() -> list[FileIndexEntry]:
    """Scan all Python and TypeScript source directories and return sorted entries."""
    entries: list[FileIndexEntry] = []
    for folder_name in PYTHON_SCAN_DIRS:
        folder = REPO_ROOT / folder_name
        if not folder.exists():
            continue
        for py_path in sorted(folder.rglob("*.py")):
            rel = str(py_path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel.startswith("api/venv/") or "/__pycache__/" in rel or rel.endswith("__init__.py"):
                continue
            entries.append(_index_py_file(py_path))

    if FRONTEND_SRC_DIR.exists():
        for ts_path in sorted(FRONTEND_SRC_DIR.rglob("*")):
            if ts_path.is_file() and ts_path.suffix in (".ts", ".tsx") and not ts_path.name.endswith(".d.ts"):
                entries.append(_index_ts_file(ts_path))
    return sorted(entries, key=lambda e: e["path"])


def _build_payload(entries: list[FileIndexEntry]) -> CodebaseIndexPayload:
    """Assemble the complete `CodebaseIndexPayload` from file entries."""
    domain_counts: dict[str, int] = {}
    dirs: set[str] = set()
    for entry in entries:
        pkg = entry["domain_package"]
        domain_counts[pkg] = domain_counts.get(pkg, 0) + 1
        parent = str(Path(entry["path"]).parent).replace("\\", "/")
        dirs.add(parent)
    return {
        "total_files": len(entries),
        "domain_packages": dict(sorted(domain_counts.items())),
        "directory_tree": sorted(dirs),
        "files": entries,
    }


def _format_symbols(entry: FileIndexEntry) -> str:
    """Format classes, functions, and endpoints into a compact Markdown table cell."""
    items = [*entry["endpoints"], *entry["classes"], *entry["functions"]]
    if not items:
        return "—"
    shown = ", ".join(f"`{s}`" for s in items[:6])
    return f"{shown} (+{len(items) - 6})" if len(items) > 6 else shown


def _render_markdown(payload: CodebaseIndexPayload) -> str:
    """Render `CODEBASE_INDEX.md` from `CodebaseIndexPayload`."""
    lines: list[str] = [
        "# Veo Generators — Codebase Index",
        "",
        f"Auto-generated by `scripts/generate_codebase_index.py`. Total indexed source files: **{payload['total_files']}**.",
        "",
        "## Domain Packages & Directory Tree",
        "",
        "| Domain Package | Source Files |",
        "| :--- | ---: |",
    ]
    for pkg, count in payload["domain_packages"].items():
        lines.append(f"| `{pkg}` | {count} |")

    lines.extend(["", "### Directories", "", "```text"])
    lines.extend(payload["directory_tree"])
    lines.extend([
        "```",
        "",
        "## File Inventory",
        "",
        "| File Path | Tier | Lines | Exported Classes / Functions / Endpoints |",
        "| :--- | :--- | ---: | :--- |",
    ])
    for entry in payload["files"]:
        syms = _format_symbols(entry)
        lines.append(
            f"| `{entry['path']}` | {entry['tier']} | {entry['non_comment_lines']} | {syms} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_index() -> CodebaseIndexPayload:
    """Generate and write `CODEBASE_INDEX.json` and `CODEBASE_INDEX.md` at `REPO_ROOT`."""
    entries = _collect_all_entries()
    payload = _build_payload(entries)
    json_path = REPO_ROOT / "CODEBASE_INDEX.json"
    md_path = REPO_ROOT / "CODEBASE_INDEX.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    """CLI entrypoint for generating the codebase index."""
    payload = generate_index()
    print(
        f"✅ Generated CODEBASE_INDEX.json and CODEBASE_INDEX.md ({payload['total_files']} files indexed)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
