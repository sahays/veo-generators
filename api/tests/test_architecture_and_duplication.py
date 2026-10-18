"""Automated tests for the AST-based static checker (duplicate code & tier-breakers)."""

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER_PATH = REPO_ROOT / "scripts" / "check_architecture.py"


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location("check_architecture", CHECKER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_architecture"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_codebase_has_no_duplicate_code_or_tier_breakers() -> None:
    """Verify the entire Python + TypeScript codebase has 0 duplicate AST blocks and 0 tier-breakers."""
    checker = _load_checker()
    violations = checker.run_all_checks()
    formatted = "\n".join(
        f"[{v.category}] {v.location}: {v.message}" for v in violations
    )
    assert not violations, f"AST Static Checker found violations:\n{formatted}"


def test_python_ast_normalizer_detects_renamed_clones() -> None:
    """Verify the Python AST canonical normalizer catches cloned functions even when variables are renamed."""
    checker = _load_checker()
    fn_a = """
def compute_metrics(items, factor):
    total = 0
    results = []
    for item in items:
        if item > 0:
            val = item * factor + 1
            total += val
            results.append(val)
    return total, results
"""
    fn_b = """
def duplicate_calculation(elements, multiplier):
    acc = 0
    out = []
    for elem in elements:
        if elem > 0:
            computed = elem * multiplier + 1
            acc += computed
            out.append(computed)
    return acc, out
"""
    tree_a = checker._CanonicalASTNormalizer().visit(ast.parse(fn_a))
    tree_b = checker._CanonicalASTNormalizer().visit(ast.parse(fn_b))
    dump_a = ast.dump(tree_a, annotate_fields=True, include_attributes=False)
    dump_b = ast.dump(tree_b, annotate_fields=True, include_attributes=False)
    assert dump_a == dump_b


def test_ts_ast_normalizer_detects_structural_clones() -> None:
    """Verify the TypeScript AST token normalizer catches structural duplicates with renamed identifiers."""
    checker = _load_checker()
    ts_a = "{ const x = a + b; if (x > 10) { return x * 2; } return 0; }"
    ts_b = "{ const y = m + n; if (y > 10) { return y * 2; } return 0; }"
    _, sig_a = checker._normalize_ts_tokens(ts_a)
    _, sig_b = checker._normalize_ts_tokens(ts_b)
    assert sig_a == sig_b


def test_tier_classification_enforces_hierarchy() -> None:
    """Verify both backend and frontend tier classifiers enforce expected hierarchy."""
    checker = _load_checker()
    assert checker.classify_backend_module(
        "api/models/models_records.py"
    ) < checker.classify_backend_module("api/storage_service.py")
    assert checker.classify_backend_module(
        "api/storage_service.py"
    ) < checker.classify_backend_module("api/routers/_crud.py")
    assert checker.classify_backend_module(
        "api/routers/_crud.py"
    ) < checker.classify_backend_module("api/routers/media/adapts.py")
    assert checker.classify_backend_module(
        "api/routers/media/adapts.py"
    ) < checker.classify_backend_module("api/main.py")

    t_types, _ = checker.classify_frontend_module("types/project.ts")
    t_ui, _ = checker.classify_frontend_module("components/ui/button.tsx")
    t_store, _ = checker.classify_frontend_module("store/useAuthStore.ts")
    t_shared, _ = checker.classify_frontend_module("components/shared/RecordCard.tsx")
    t_pages, dom_a = checker.classify_frontend_module(
        "components/pages/adapts/AdaptVariantGrid.tsx"
    )
    t_app, _ = checker.classify_frontend_module("App.tsx")

    assert t_types < t_ui < t_store < t_shared < t_pages < t_app
    assert dom_a == "adapts"


def test_codebase_has_no_ui_component_lapses() -> None:
    """Verify no raw <button>, <textarea>, <select>, or text <input> elements exist outside components/ui/."""
    comp_checker_path = REPO_ROOT / "scripts" / "check_components.py"
    spec = importlib.util.spec_from_file_location("check_components", comp_checker_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_components"] = mod
    spec.loader.exec_module(mod)
    violations = mod.check_frontend_components()
    formatted = "\n".join(f"[{v.rule}] {v.location}: {v.message}" for v in violations)
    assert not violations, f"UI Component Checker found lapses:\n{formatted}"


def test_codebase_index_checker_detects_added_moved_deleted_files() -> None:
    """Verify check_codebase_index detects unindexed, phantom (deleted/moved), and stale files."""
    idx_checker_path = REPO_ROOT / "scripts" / "check_codebase_index.py"
    spec = importlib.util.spec_from_file_location(
        "check_codebase_index", idx_checker_path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_codebase_index"] = mod
    spec.loader.exec_module(mod)

    base_entry = {
        "path": "api/main.py",
        "tier": "T4:Entry",
        "lines": 100,
        "classes": [],
        "functions": ["health"],
        "endpoints": ["GET /health"],
    }
    live_map = {
        "api/main.py": {**base_entry, "functions": ["health", "ready"]},
        "api/new_module.py": {**base_entry, "path": "api/new_module.py"},
    }
    disk_map = {
        "api/main.py": base_entry,
        "api/deleted_module.py": {**base_entry, "path": "api/deleted_module.py"},
    }
    drifts = mod._compare_file_entries(live_map, disk_map)
    categories = {(d.category, d.path) for d in drifts}
    assert ("UNINDEXED_FILE", "api/new_module.py") in categories
    assert ("PHANTOM_FILE", "api/deleted_module.py") in categories
    assert ("STALE_METADATA", "api/main.py") in categories
