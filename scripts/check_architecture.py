#!/usr/bin/env python3
"""AST-based static analyzer for duplicate code and architectural tier-breakers.

Checks both:
1. Python Backend (`api/`, `workers/`) using the standard `ast` module:
   - Enforces strict 5-tier top-down import architecture.
   - Detects duplicate functions/methods via canonicalized AST subtree hashing.
2. TypeScript/React Frontend (`frontend/src/`) using lexical/syntactic AST parsing:
   - Enforces strict 6-tier top-down import architecture + horizontal feature isolation.
   - Detects duplicate component/function implementations across files.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
WORKERS_DIR = REPO_ROOT / "workers"
FRONTEND_SRC_DIR = REPO_ROOT / "frontend" / "src"


@dataclass(frozen=True)
class Violation:
    category: str  # "tier-breaker" | "duplicate-code"
    location: str
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# 1. Backend Python AST Tier & Duplication Analyzer
# ─────────────────────────────────────────────────────────────────────────────

BACKEND_TIER_NAMES = {
    1: "Tier 1 (Models & Pure Config)",
    2: "Tier 2 (Core Services & Deps)",
    3: "Tier 3 (Shared Router Helpers)",
    4: "Tier 4 (Feature Routers & Agents)",
    5: "Tier 5 (Entrypoints, Scripts & Workers)",
}


def classify_backend_module(rel_path: str) -> int | None:
    """Return the architectural tier (1..5) for a Python file relative to REPO_ROOT."""
    rel = rel_path.replace("\\", "/")
    if rel.startswith("api/venv/") or rel.startswith("api/tests/"):
        return None
    if "/__pycache__/" in rel or rel.endswith("__init__.py"):
        return None

    if rel.startswith("api/models") or rel == "api/pricing_config.py":
        return 1
    if rel == "api/main.py" or rel.startswith("workers/") or rel.startswith("api/scripts/"):
        return 5
    if rel in ("api/routers/_crud.py", "api/routers/render_helpers.py"):
        return 3
    if rel.startswith("api/routers/") or rel.startswith("api/agents/"):
        return 4
    return 2


def resolve_backend_import(module_name: str) -> str | None:
    """Resolve an import target like `routers.adapts` or `deps` to a repo-relative path."""
    parts = module_name.split(".")
    for base_prefix in ("api", "workers"):
        candidate_py = REPO_ROOT / base_prefix / ("/".join(parts) + ".py")
        if candidate_py.is_file():
            return str(candidate_py.relative_to(REPO_ROOT)).replace("\\", "/")
        candidate_pkg = REPO_ROOT / base_prefix / ("/".join(parts)) / "__init__.py"
        if candidate_pkg.is_file():
            return str(candidate_pkg.relative_to(REPO_ROOT)).replace("\\", "/")
    direct_py = REPO_ROOT / ("/".join(parts) + ".py")
    if direct_py.is_file():
        return str(direct_py.relative_to(REPO_ROOT)).replace("\\", "/")
    return None


class _CanonicalASTNormalizer(ast.NodeTransformer):
    """Normalizes a Python function AST to detect structural clones."""

    def __init__(self) -> None:
        super().__init__()
        self._var_map: dict[str, str] = {}

    def _norm_name(self, name: str) -> str:
        if name in ("self", "cls"):
            return name
        if name not in self._var_map:
            self._var_map[name] = f"_v{len(self._var_map)}"
        return self._var_map[name]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._normalize_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._normalize_func(node)

    def _normalize_func(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ast.AST:
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]

        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            arg.arg = self._norm_name(arg.arg)
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.arg = self._norm_name(node.args.vararg.arg)
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.arg = self._norm_name(node.args.kwarg.arg)
            node.args.kwarg.annotation = None

        node.name = "_fn"
        node.returns = None
        node.decorator_list = []
        node.body = [self.visit(stmt) for stmt in body]
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, (ast.Store, ast.Param)) or node.id in self._var_map:
            node.id = self._norm_name(node.id)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._norm_name(node.arg)
        node.annotation = None
        return node


def analyze_python_ast() -> list[Violation]:
    violations: list[Violation] = []
    seen_hashes: dict[str, tuple[str, str, int]] = {}

    py_files: list[Path] = []
    for folder in (API_DIR, WORKERS_DIR):
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel.startswith("api/venv/") or "/__pycache__/" in rel:
                continue
            py_files.append(path)

    for path in py_files:
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            violations.append(
                Violation("syntax-error", f"{rel}:{exc.lineno}", str(exc))
            )
            continue

        src_tier = classify_backend_module(rel)

        # 1. Check top-level module imports for tier-breakers
        if src_tier is not None:
            for stmt in tree.body:
                imported_modules: list[tuple[str, int]] = []
                if isinstance(stmt, ast.Import):
                    for alias in stmt.names:
                        imported_modules.append((alias.name, stmt.lineno))
                elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                    imported_modules.append((stmt.module, stmt.lineno))
                    for alias in stmt.names:
                        imported_modules.append(
                            (f"{stmt.module}.{alias.name}", stmt.lineno)
                        )

                for mod_name, lineno in imported_modules:
                    target_rel = resolve_backend_import(mod_name)
                    if not target_rel or target_rel == rel:
                        continue
                    target_tier = classify_backend_module(target_rel)
                    if target_tier is not None and target_tier > src_tier:
                        violations.append(
                            Violation(
                                "tier-breaker",
                                f"{rel}:{lineno}",
                                f"{BACKEND_TIER_NAMES[src_tier]} module '{rel}' "
                                f"imports higher-tier {BACKEND_TIER_NAMES[target_tier]} module '{target_rel}'",
                            )
                        )

        # 2. Check function/method ASTs for duplicate code (skip test files)
        if rel.startswith("api/tests/"):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stmts = [
                    s
                    for s in node.body
                    if not (
                        isinstance(s, ast.Expr)
                        and isinstance(s.value, ast.Constant)
                        and isinstance(s.value.value, str)
                    )
                ]
                if len(stmts) < 6:
                    continue
                node_count = sum(1 for _ in ast.walk(node))
                if node_count < 40:
                    continue

                cloned = ast.parse(ast.unparse(node))
                norm_tree = _CanonicalASTNormalizer().visit(cloned)
                canonical_dump = ast.dump(
                    norm_tree, annotate_fields=True, include_attributes=False
                )
                digest = hashlib.sha256(canonical_dump.encode("utf-8")).hexdigest()

                if digest in seen_hashes:
                    prev_rel, prev_name, prev_line = seen_hashes[digest]
                    violations.append(
                        Violation(
                            "duplicate-code",
                            f"{rel}:{node.lineno}",
                            f"Function '{node.name}' in {rel}:{node.lineno} is an AST clone of "
                            f"'{prev_name}' in {prev_rel}:{prev_line}",
                        )
                    )
                else:
                    seen_hashes[digest] = (rel, node.name, node.lineno)

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# 2. Frontend TypeScript/TSX AST Tier & Duplication Analyzer
# ─────────────────────────────────────────────────────────────────────────────

FRONTEND_TIER_NAMES = {
    1: "Tier 1 (Types, Schemas & Pure Utils)",
    2: "Tier 2 (Shadcn UI Primitives)",
    3: "Tier 3 (State Stores & Client Services)",
    4: "Tier 4 (Shared Hooks & Domain Shells)",
    5: "Tier 5 (Feature Pages & Domain Views)",
    6: "Tier 6 (Next.js App Entrypoints & Root Router)",
}

_IMPORT_RE = re.compile(
    r"^\s*(?:import|export)\s+(?!type\b)(?:[^'\"\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

_COMMENT_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_FUNC_DECL_RE = re.compile(
    r"(?:export\s+)?(?:const|function)\s+([A-Za-z0-9_]+)\s*(?:=\s*(?:async\s*)?(?:<[^>]+>\s*)?\([^)]*\)\s*(?::\s*[^=]+)?=>|\([^)]*\)\s*(?::\s*[^{]+)?\{)"
)


def classify_frontend_module(rel_path: str) -> tuple[int, str | None]:
    """Return (tier, feature_domain) for a file relative to `frontend/src/`."""
    rel = rel_path.replace("\\", "/")
    if rel.startswith("types/") or rel == "lib/utils.ts":
        return 1, None
    if rel.startswith("components/ui/") or rel in (
        "components/Common.tsx",
        "components/UI.tsx",
        "components/Modal.tsx",
    ):
        return 2, None
    if (
        rel.startswith("store/")
        or rel.startswith("lib/api/")
        or rel in ("lib/api.ts", "lib/captureFrames.ts")
        or rel.startswith("components/avatar/live/")
    ):
        return 3, None
    if (
        rel.startswith("hooks/")
        or rel.startswith("components/shared/")
        or rel.startswith("components/pricing/")
        or rel in ("components/ModelPill.tsx", "components/ModelRegionPicker.tsx")
    ):
        return 4, None
    if rel.startswith("app/") or rel == "App.tsx":
        return 6, None

    # Tier 5: Feature Pages & Domain Modules
    m_page_sub = re.match(r"^components/pages/([a-zA-Z0-9_]+)/", rel)
    if m_page_sub:
        return 5, m_page_sub.group(1).lower()
    if rel.startswith("components/ads/"):
        return 5, "ads"
    if rel.startswith("components/avatar/"):
        return 5, "avatar"
    if rel.startswith("components/chat/"):
        return 5, "chat"
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


def _extract_brace_block(text: str, start_idx: int) -> str | None:
    """Extract a balanced `{ ... }` or `=> ( ... )` body starting at `start_idx`."""
    idx = start_idx
    while idx < len(text) and text[idx] not in "{(":
        idx += 1
    if idx >= len(text):
        return None
    open_ch = text[idx]
    close_ch = "}" if open_ch == "{" else ")"
    depth = 0
    in_str: str | None = None
    i = idx
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"', "`"):
                in_str = ch
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[idx : i + 1]
        i += 1
    return None


def _normalize_ts_tokens(code: str) -> tuple[list[str], str]:
    """Tokenize and canonicalize a TypeScript/TSX body for structural clone detection."""
    tokens = re.findall(
        r"[A-Za-z_$][A-Za-z0-9_$]*|\d+(?:\.\d+)?|==|!=|<=|>=|=>|&&|\|\||[^\s]",
        code,
    )
    keywords = {
        "const", "let", "var", "function", "return", "if", "else", "for", "while",
        "switch", "case", "break", "continue", "try", "catch", "finally", "throw",
        "new", "async", "await", "true", "false", "null", "undefined", "void",
        "typeof", "instanceof", "in", "of", "class", "extends", "super", "import",
        "export", "default", "from", "as",
    }
    var_map: dict[str, str] = {}
    norm: list[str] = []
    for idx, tok in enumerate(tokens):
        prev_tok = tokens[idx - 1] if idx > 0 else ""
        if re.match(r"^[a-z_$][A-Za-z0-9_$]*$", tok) and tok not in keywords:
            if prev_tok in (".", "<", "</"):
                norm.append(tok)
            else:
                if tok not in var_map:
                    var_map[tok] = f"$v{len(var_map)}"
                norm.append(var_map[tok])
        else:
            norm.append(tok)
    return tokens, " ".join(norm)


def analyze_frontend_ast() -> list[Violation]:
    violations: list[Violation] = []
    if not FRONTEND_SRC_DIR.exists():
        return violations

    ts_files = sorted(
        p
        for p in FRONTEND_SRC_DIR.rglob("*")
        if p.suffix in (".ts", ".tsx") and not p.name.endswith(".d.ts")
    )

    seen_ts_blocks: dict[str, tuple[str, str, int]] = {}

    for path in ts_files:
        rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
        rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        raw = path.read_text(encoding="utf-8")
        clean = _COMMENT_RE.sub("", raw)

        src_tier, src_domain = classify_frontend_module(rel_src)

        # 1. Check imports for Tier-Breakers and Cross-Feature Violations
        for match in _IMPORT_RE.finditer(clean):
            spec = match.group(1)
            target_path = resolve_frontend_import(path, spec)
            if not target_path or target_path == path:
                continue
            target_rel_src = str(
                target_path.relative_to(FRONTEND_SRC_DIR)
            ).replace("\\", "/")
            target_tier, target_domain = classify_frontend_module(target_rel_src)
            lineno = raw[: match.start()].count("\n") + 1

            if target_tier > src_tier:
                violations.append(
                    Violation(
                        "tier-breaker",
                        f"{rel_repo}:{lineno}",
                        f"{FRONTEND_TIER_NAMES[src_tier]} file '{rel_src}' "
                        f"cannot import higher-tier {FRONTEND_TIER_NAMES[target_tier]} file '{target_rel_src}'",
                    )
                )
            elif (
                src_tier == 5
                and target_tier == 5
                and src_domain
                and target_domain
                and src_domain != target_domain
            ):
                violations.append(
                    Violation(
                        "tier-breaker",
                        f"{rel_repo}:{lineno}",
                        f"Cross-feature import violation: '{rel_src}' (domain '{src_domain}') "
                        f"cannot import from sibling feature domain '{target_domain}' ('{target_rel_src}')",
                    )
                )

        # 2. Check for duplicate functions/components across files
        for match in _FUNC_DECL_RE.finditer(clean):
            fn_name = match.group(1)
            lineno = raw[: match.start()].count("\n") + 1
            body = _extract_brace_block(clean, match.end() - 1)
            if not body:
                continue
            raw_tokens, norm_sig = _normalize_ts_tokens(body)
            if len(raw_tokens) < 65:
                continue
            digest = hashlib.sha256(norm_sig.encode("utf-8")).hexdigest()
            if digest in seen_ts_blocks:
                prev_file, prev_fn, prev_line = seen_ts_blocks[digest]
                if prev_file != rel_repo:
                    violations.append(
                        Violation(
                            "duplicate-code",
                            f"{rel_repo}:{lineno}",
                            f"Component/Function '{fn_name}' in {rel_repo}:{lineno} "
                            f"is a structural AST duplicate of '{prev_fn}' in {prev_file}:{prev_line}",
                        )
                    )
            else:
                seen_ts_blocks[digest] = (rel_repo, fn_name, lineno)

    return violations


def run_all_checks() -> list[Violation]:
    return analyze_python_ast() + analyze_frontend_ast()


def main() -> int:
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
