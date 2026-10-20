"""Architectural tier classifiers and import hierarchy analyzers for Python and TypeScript."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .ast_clones import check_py_clones_and_limits, check_ts_clones
from .models import FRONTEND_SRC_DIR, REPO_ROOT, TS_COMMENT_RE, Violation

_BACKEND_DIRS: tuple[Path, ...] = (
    REPO_ROOT / "api",
    REPO_ROOT / "workers",
    REPO_ROOT / "agents_service",
    REPO_ROOT / "productions_service",
)

_FORBIDDEN_AGENT_IMPORT_PREFIXES: tuple[str, ...] = (
    "api/deps.py",
    "api/firestore_service.py",
    "api/storage_service.py",
    "api/gemini_service.py",
    "api/video_service.py",
    "api/pricing_config.py",
    "api/reframe_strategies.py",
    "api/models",
    "api/routers/",
    "workers/",
)

BACKEND_TIER_NAMES: dict[int, str] = {
    1: "Tier 1 (Models & Pure Config)",
    2: "Tier 2 (Core Services & Deps)",
    3: "Tier 3 (Shared Router Helpers)",
    4: "Tier 4 (Feature Routers & Agents)",
    5: "Tier 5 (Entrypoints, Scripts & Workers)",
}

FRONTEND_TIER_NAMES: dict[int, str] = {
    1: "Tier 1 (Types, Schemas & Pure Utils)",
    2: "Tier 2 (Shadcn UI Primitives)",
    3: "Tier 3 (State Stores & Client Services)",
    4: "Tier 4 (Shared Hooks & Domain Shells)",
    5: "Tier 5 (Feature Pages & Domain Views)",
    6: "Tier 6 (Next.js App Entrypoints & Root Router)",
}

_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:import|export)\s+(?!type\b)(?:[^'\"\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

_BACKEND_SKIP_PREFIXES: tuple[str, ...] = (
    "api/venv/",
    "api/tests/",
    "productions_service/tests/",
)
_BACKEND_TIER_1_EXACT: frozenset[str] = frozenset(
    {
        "api/pricing_config.py",
        "productions_service/storygraph/errors.py",
        "productions_service/storygraph/config.py",
        "productions_service/storygraph/schema.py",
    }
)
_BACKEND_TIER_1_PREFIXES: tuple[str, ...] = (
    "api/models",
    "productions_service/storygraph/schemas/",
)
_BACKEND_TIER_5_EXACT: frozenset[str] = frozenset(
    {
        "api/main.py",
        "agents_service/main.py",
        "productions_service/main.py",
        "productions_service/storygraph/repair/loop.py",
    }
)
_BACKEND_TIER_5_PREFIXES: tuple[str, ...] = (
    "workers/",
    "api/scripts/",
    "productions_service/storygraph/pipeline/",
    "productions_service/services/",
    "productions_service/routers/",
)
_BACKEND_TIER_3_EXACT: frozenset[str] = frozenset(
    {
        "api/routers/_crud.py",
        "api/routers/render_helpers.py",
        "productions_service/storygraph/budget.py",
        "productions_service/storygraph/compile.py",
        "productions_service/storygraph/assemble.py",
    }
)
_BACKEND_TIER_3_PREFIXES: tuple[str, ...] = (
    "productions_service/storygraph/tools/",
    "productions_service/storygraph/adapters/",
)
_BACKEND_TIER_4_PREFIXES: tuple[str, ...] = (
    "api/routers/",
    "api/agents/",
    "productions_service/storygraph/agents/",
)


def classify_backend_module(rel_path: str) -> int | None:
    """Return the architectural tier (1..5) for a Python file relative to REPO_ROOT."""
    rel = rel_path.replace("\\", "/")
    if (
        rel.startswith(_BACKEND_SKIP_PREFIXES)
        or "/__pycache__/" in rel
        or rel.endswith("__init__.py")
    ):
        return None
    if rel.startswith(_BACKEND_TIER_1_PREFIXES) or rel in _BACKEND_TIER_1_EXACT:
        return 1
    if rel in _BACKEND_TIER_5_EXACT or rel.startswith(_BACKEND_TIER_5_PREFIXES):
        return 5
    if rel in _BACKEND_TIER_3_EXACT or rel.startswith(_BACKEND_TIER_3_PREFIXES):
        return 3
    if rel.startswith(_BACKEND_TIER_4_PREFIXES):
        return 4
    return 2


def resolve_backend_import(module_name: str) -> str | None:
    """Resolve an import target like `routers.adapts` or `deps` to a repo-relative path."""
    rel_sub = "/".join(module_name.split("."))
    for base_prefix in ("api", "workers", "agents_service", "productions_service"):
        for suffix in (f"{rel_sub}.py", f"{rel_sub}/__init__.py"):
            candidate = REPO_ROOT / base_prefix / suffix
            if candidate.is_file():
                return str(candidate.relative_to(REPO_ROOT)).replace("\\", "/")
    direct_py = REPO_ROOT / f"{rel_sub}.py"
    if direct_py.is_file():
        return str(direct_py.relative_to(REPO_ROOT)).replace("\\", "/")
    return None


def _collect_top_level_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Extract top-level import module targets and line numbers from a Python module."""
    imported: list[tuple[str, int]] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                imported.append((alias.name, stmt.lineno))
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            imported.append((stmt.module, stmt.lineno))
            for alias in stmt.names:
                imported.append((f"{stmt.module}.{alias.name}", stmt.lineno))
    return imported


def _check_backend_file_imports(
    tree: ast.Module, rel: str, src_tier: int | None
) -> list[Violation]:
    """Check a Python file's imports for tier-breakers and agent isolation."""
    is_agent = rel.startswith(("api/agents/", "agents_service/"))
    if src_tier is None and not is_agent:
        return []
    violations: list[Violation] = []
    for mod_name, lineno in _collect_top_level_imports(tree):
        target_rel = resolve_backend_import(mod_name)
        if not target_rel or target_rel == rel:
            continue
        if is_agent and target_rel.startswith(_FORBIDDEN_AGENT_IMPORT_PREFIXES):
            msg = f"Agent module '{rel}' cannot directly import backend internal module '{target_rel}' (must use REST API tools)"
            violations.append(Violation("tier-breaker", f"{rel}:{lineno}", msg))
            continue
        target_tier = classify_backend_module(target_rel)
        if src_tier is not None and target_tier is not None and target_tier > src_tier:
            msg = (
                f"{BACKEND_TIER_NAMES[src_tier]} module '{rel}' "
                f"imports higher-tier {BACKEND_TIER_NAMES[target_tier]} module '{target_rel}'"
            )
            violations.append(Violation("tier-breaker", f"{rel}:{lineno}", msg))
    return violations


def _iter_backend_py_files() -> list[Path]:
    """Collect all non-venv Python files across backend services."""
    py_files: list[Path] = []
    for folder in _BACKEND_DIRS:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if not (rel.startswith("api/venv/") or "/__pycache__/" in rel):
                py_files.append(path)
    return py_files


def analyze_python_ast() -> list[Violation]:
    """Analyze all backend Python files for tier-breakers, AST clones, and statement limits."""
    violations: list[Violation] = []
    seen_hashes: dict[str, tuple[str, str, int]] = {}
    for path in _iter_backend_py_files():
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            violations.append(
                Violation("syntax-error", f"{rel}:{exc.lineno}", str(exc))
            )
            continue
        violations.extend(
            _check_backend_file_imports(tree, rel, classify_backend_module(rel))
        )
        if not rel.startswith(("api/tests/", "productions_service/tests/")):
            violations.extend(check_py_clones_and_limits(tree, rel, seen_hashes))
    return violations


_FE_FIXED_TIERS: tuple[tuple[tuple[str, ...], tuple[str, ...], int], ...] = (
    (("types/",), ("lib/utils.ts",), 1),
    (
        ("components/ui/",),
        ("components/Common.tsx", "components/UI.tsx", "components/Modal.tsx"),
        2,
    ),
    (
        ("store/", "lib/api/", "components/avatar/live/"),
        ("lib/api.ts", "lib/captureFrames.ts"),
        3,
    ),
    (
        ("hooks/", "components/shared/", "components/pricing/"),
        ("components/ModelPill.tsx", "components/ModelRegionPicker.tsx"),
        4,
    ),
    (("app/",), ("App.tsx",), 6),
)


def classify_frontend_module(rel_path: str) -> tuple[int, str | None]:
    """Return (tier, feature_domain) for a file relative to `frontend/src/`."""
    rel = rel_path.replace("\\", "/")
    for prefixes, exacts, tier in _FE_FIXED_TIERS:
        if rel.startswith(prefixes) or rel in exacts:
            return tier, None
    m_page_sub = re.match(r"^components/pages/([a-zA-Z0-9_]+)/", rel)
    if m_page_sub:
        return 5, m_page_sub.group(1).lower()
    for dom in ("ads", "avatar", "chat"):
        if rel.startswith(f"components/{dom}/"):
            return 5, dom
    return 5, None


def resolve_frontend_import(source_file: Path, spec: str) -> Path | None:
    """Resolve `@/...` or relative imports inside `frontend/src/`."""
    if spec.startswith("@/"):
        base = FRONTEND_SRC_DIR / spec[2:]
    elif spec.startswith("."):
        base = (source_file.parent / spec).resolve()
    else:
        return None
    for ext in ("", ".ts", ".tsx", "/index.ts", "/index.tsx"):
        candidate = Path(str(base) + ext)
        if candidate.is_file():
            return candidate
    return None


def _check_frontend_file_imports(
    path: Path, raw: str, clean: str, rel_src: str, rel_repo: str
) -> list[Violation]:
    """Check a frontend file's imports for tier-breakers and cross-feature violations."""
    src_tier, src_domain = classify_frontend_module(rel_src)
    violations: list[Violation] = []
    for match in _IMPORT_RE.finditer(clean):
        target_path = resolve_frontend_import(path, match.group(1))
        if not target_path or target_path == path:
            continue
        target_rel_src = str(target_path.relative_to(FRONTEND_SRC_DIR)).replace(
            "\\", "/"
        )
        target_tier, target_domain = classify_frontend_module(target_rel_src)
        lineno = raw[: match.start()].count("\n") + 1
        if target_tier > src_tier:
            msg = (
                f"{FRONTEND_TIER_NAMES[src_tier]} file '{rel_src}' "
                f"cannot import higher-tier {FRONTEND_TIER_NAMES[target_tier]} file '{target_rel_src}'"
            )
            violations.append(Violation("tier-breaker", f"{rel_repo}:{lineno}", msg))
        elif (
            src_tier == 5
            and target_tier == 5
            and src_domain
            and target_domain
            and src_domain != target_domain
        ):
            msg = (
                f"Cross-feature import violation: '{rel_src}' (domain '{src_domain}') "
                f"cannot import from sibling feature domain '{target_domain}' ('{target_rel_src}')"
            )
            violations.append(Violation("tier-breaker", f"{rel_repo}:{lineno}", msg))
    return violations


def analyze_frontend_ast() -> list[Violation]:
    """Analyze all TypeScript/TSX files under `frontend/src/` for tier-breakers and clones."""
    if not FRONTEND_SRC_DIR.exists():
        return []
    ts_files = sorted(
        p
        for p in FRONTEND_SRC_DIR.rglob("*")
        if p.suffix in (".ts", ".tsx") and not p.name.endswith(".d.ts")
    )
    violations: list[Violation] = []
    seen_ts_blocks: dict[str, tuple[str, str, int]] = {}
    for path in ts_files:
        rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
        rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        raw = path.read_text(encoding="utf-8")
        clean = TS_COMMENT_RE.sub("", raw)
        violations.extend(
            _check_frontend_file_imports(path, raw, clean, rel_src, rel_repo)
        )
        violations.extend(check_ts_clones(raw, clean, rel_repo, seen_ts_blocks))
    return violations
