#!/usr/bin/env python3
"""AST-based static analyzer for duplicate code and architectural tier-breakers.

Checks both:
1. Python Backend (`api/`, `workers/`, `agents_service/`, `productions_service/`)
2. TypeScript/React Frontend (`frontend/src/`)
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from checkers.arch_tiers import (  # noqa: E402
    BACKEND_TIER_NAMES,
    FRONTEND_TIER_NAMES,
    analyze_frontend_ast,
    analyze_python_ast,
    classify_backend_module,
    classify_frontend_module,
    resolve_backend_import,
    resolve_frontend_import,
)
from checkers.ast_clones import (  # noqa: E402
    _CanonicalASTNormalizer,
    _normalize_ts_tokens,
)
from checkers.models import FRONTEND_SRC_DIR, REPO_ROOT, Violation  # noqa: E402

__all__ = [
    "BACKEND_TIER_NAMES",
    "FRONTEND_SRC_DIR",
    "FRONTEND_TIER_NAMES",
    "REPO_ROOT",
    "Violation",
    "_CanonicalASTNormalizer",
    "_normalize_ts_tokens",
    "analyze_frontend_ast",
    "analyze_python_ast",
    "classify_backend_module",
    "classify_frontend_module",
    "resolve_backend_import",
    "resolve_frontend_import",
    "run_all_checks",
]


def run_all_checks() -> list[Violation]:
    """Run both Python and TypeScript AST tier and duplication checks."""
    return analyze_python_ast() + analyze_frontend_ast()


def main() -> int:
    """CLI entrypoint for AST static architecture and duplication checks."""
    violations = run_all_checks()
    if not violations:
        print("✅ AST Static Checker: 0 duplicate code blocks, 0 tier-breakers found.")
        return 0

    print(f"❌ AST Static Checker found {len(violations)} violation(s):")
    for v in violations:
        print(f"  [{v.category}] {v.location}: {v.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
