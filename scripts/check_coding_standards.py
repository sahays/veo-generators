#!/usr/bin/env python3
"""Repository-wide coding standards enforcement runner.

Enforces all coding instructions from GEMINI.md across Python and TypeScript:
- `no-brute-force`: Zero `.index()` calls in loops or large list-literal membership in nested loops
- `owasp-top-10`: Zero `eval`/`exec`/`pickle.loads`/`shell=True`/`verify=False`/`dangerouslySetInnerHTML`
- `tier-separation-of-concerns`: Cascaded Controller -> Service -> Repo/Adapter -> Infra & UI -> Store/Hook -> API
- `file-size-limit`: <= 400 non-comment lines/statements per file
- `function-size-limit`: <= 30 non-comment lines/statements per function
- `strict-typing`: 100% parameter + return annotations in Python; zero explicit `any` in TypeScript
- `folder-structure`: Zero flat file dumps (> 15 source files in a single directory)
- `semantic-logging`: Logs must include structured context answering Who, Where, What, When, Why, and How
- `no-vanity-tests`: Tests must verify meaningful behavioral outcomes and edge cases, not superficial checks
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from checkers import (
    FRONTEND_SRC_DIR,
    PYTHON_SCAN_DIRS,
    REPO_ROOT,
    CodingViolation,
    check_folder_organization,
    check_python_no_brute_force,
    check_python_no_vanity_tests,
    check_python_owasp,
    check_python_semantic_logging,
    check_python_size_and_types,
    check_python_tier_isolation,
    check_ts_owasp_and_db_tier,
    check_ts_semantic_logging,
    check_ts_size_and_types,
    check_ts_tier_isolation,
)

ALL_RULES: tuple[str, ...] = (
    "no-brute-force",
    "owasp-top-10",
    "tier-separation-of-concerns",
    "file-size-limit",
    "function-size-limit",
    "strict-typing",
    "folder-structure",
    "semantic-logging",
    "no-vanity-tests",
)


def _iter_python_files() -> list[Path]:
    """Collect all non-venv Python source files (including tests) across the repository."""
    files: list[Path] = []
    for folder_name in PYTHON_SCAN_DIRS:
        folder = REPO_ROOT / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if (
                rel.startswith("api/venv/")
                or "/__pycache__/" in rel
                or rel.endswith("__init__.py")
            ):
                continue
            files.append(path)
    return files


def _iter_ts_files() -> list[Path]:
    """Collect all TypeScript source files under `frontend/src/`."""
    if not FRONTEND_SRC_DIR.exists():
        return []
    return sorted(
        p
        for p in FRONTEND_SRC_DIR.rglob("*")
        if p.is_file() and p.suffix in (".ts", ".tsx") and not p.name.endswith(".d.ts")
    )


def _check_python_file(py_path: Path) -> list[CodingViolation]:
    """Run all Python coding standard checks on a single file."""
    rel = str(py_path.relative_to(REPO_ROOT)).replace("\\", "/")
    source = py_path.read_text(encoding="utf-8")
    return [
        *check_python_no_brute_force(source, rel),
        *check_python_owasp(source, rel),
        *check_python_tier_isolation(source, rel),
        *check_python_size_and_types(source, rel, enforce_strict_body=True),
        *check_python_semantic_logging(source, rel),
        *check_python_no_vanity_tests(source, rel),
    ]


def _check_ts_file(ts_path: Path) -> list[CodingViolation]:
    """Run all TypeScript coding standard checks on a single file."""
    rel = str(ts_path.relative_to(REPO_ROOT)).replace("\\", "/")
    source = ts_path.read_text(encoding="utf-8")
    return [
        *check_ts_owasp_and_db_tier(source, rel),
        *check_ts_tier_isolation(source, rel),
        *check_ts_size_and_types(source, rel, enforce_no_any=True),
        *check_ts_semantic_logging(source, rel),
    ]


def run_all_coding_checks() -> list[CodingViolation]:
    """Execute all coding standard checks across the entire codebase."""
    violations: list[CodingViolation] = []
    for py_path in _iter_python_files():
        violations.extend(_check_python_file(py_path))
    for ts_path in _iter_ts_files():
        violations.extend(_check_ts_file(ts_path))
    violations.extend(check_folder_organization(REPO_ROOT))
    return violations


def _file_key(location: str) -> str:
    """Extract the file or folder path from a `path:line` location string."""
    return location.split(":", 1)[0]


def _print_report(violations: list[CodingViolation], py_count: int, ts_count: int) -> None:
    """Print a structured breakdown of violations and failing files per rule."""
    by_rule_locs: dict[str, list[CodingViolation]] = defaultdict(list)
    by_rule_files: dict[str, set[str]] = defaultdict(set)
    all_failed_files: set[str] = set()

    for v in violations:
        fk = _file_key(v.location)
        rule_key = (
            "tier-separation-of-concerns" if v.rule == "tier-db-isolation" else v.rule
        )
        by_rule_locs[rule_key].append(v)
        by_rule_files[rule_key].add(fk)
        all_failed_files.add(fk)

    print(
        f"📊 Scanned {py_count + ts_count} source files ({py_count} Python, {ts_count} TypeScript)."
    )
    if not violations:
        print("✅ All coding standards passed with 0 violations!")
        return

    print(
        f"❌ Found {len(violations)} total violation(s) across {len(all_failed_files)} unique file(s)/folder(s):\n"
    )
    for rule in ALL_RULES:
        v_list = by_rule_locs.get(rule, [])
        f_set = by_rule_files.get(rule, set())
        print(
            f"  • {rule:<28} : {len(f_set):>3} failing file(s)/dir(s) | {len(v_list):>4} violation(s)"
        )


def main() -> int:
    """CLI entrypoint returning 0 when clean or 1 when violations exist."""
    py_files = _iter_python_files()
    ts_files = _iter_ts_files()
    violations = run_all_coding_checks()
    _print_report(violations, len(py_files), len(ts_files))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
