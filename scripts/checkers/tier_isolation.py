"""Cascaded and cross-cutting Separation of Concerns (Tier Isolation) checker.

Enforces strict layered architecture across Python and TypeScript:
1. `router-calls-repo-or-infra-directly`: Routers/entrypoints bypassing Service layer
   to call Firestore/Storage repositories or raw infra (`subprocess`, `ffmpeg_runner`).
2. `domain-bypasses-repo-or-adapter`: Pure domain/agent/pipeline modules directly
   importing raw infrastructure (`google.cloud.*`, `subprocess`, `firestore_service`).
3. `component-calls-api-or-db-directly`: Frontend UI components/pages importing
   `@/lib/api` or DB SDKs directly instead of going through stores/hooks.
4. `upward-layer-import`: Lower-tier modules (`models`, `schemas`, `store`, `adapters`)
   importing higher-tier modules (`routers`, `workers`, `main`, `pipeline`, `agents`).
"""

from __future__ import annotations

import ast
import re

from .models import CodingViolation, strip_ts_comments_preserve_lines

_ROUTER_FORBIDDEN_TARGETS: tuple[str, ...] = (
    "require_firestore",
    "firestore_service",
    "storage_service",
    "FirestoreStoryGraphStore",
    "ffmpeg_runner",
    "google.cloud.firestore",
    "google.cloud.storage",
    "subprocess",
)
_DEPS_INFRA_ATTRS: tuple[str, ...] = (
    "firestore_service",
    "storage_service",
    "gemini_service",
    "video_service",
)
_DOMAIN_FORBIDDEN_INFRA: tuple[str, ...] = (
    "google.cloud.firestore",
    "google.cloud.storage",
    "subprocess",
    "firestore_service",
    "storage_service",
)
_HIGHER_TIER_MARKERS: tuple[str, ...] = (
    "routers",
    "workers",
    "main",
    "pipeline",
    "agents",
)
_TS_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:import|export)\s+(?!type\b)(?:[^'\"\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_FORBIDDEN_TS_DB_SDKS: tuple[str, ...] = (
    "@google-cloud/firestore",
    "@google-cloud/storage",
    "firebase-admin",
    "pg",
    "mongodb",
)


def _extract_py_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Return all `(imported_symbol_or_module, lineno)` pairs from a Python AST."""
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                imports.append((mod, node.lineno))
            for alias in node.names:
                imports.append(
                    (f"{mod}.{alias.name}" if mod else alias.name, node.lineno)
                )
                imports.append((alias.name, node.lineno))
    return imports


def _is_router_or_entrypoint(rel: str) -> bool:
    """Return True if `rel` is an HTTP router or service entrypoint."""
    return rel.startswith(("api/routers/", "productions_service/routers/")) or rel in (
        "api/main.py",
        "productions_service/main.py",
        "agents_service/main.py",
    )


def _is_domain_or_agent_module(rel: str) -> bool:
    """Return True if `rel` is a domain/agent/pipeline module that must use adapters/repos."""
    return rel.startswith(
        ("api/reframe_", "api/dubbing_", "api/agents/")
    ) or rel.startswith(
        (
            "productions_service/storygraph/agents/",
            "productions_service/storygraph/tools/",
            "productions_service/storygraph/pipeline/",
        )
    )


def _is_low_tier_module(rel: str) -> bool:
    """Return True if `rel` is a model, schema, repository, store, or adapter module."""
    return (
        rel.startswith(("api/models", "api/schemas/"))
        or rel in ("api/firestore_service.py", "api/storage_service.py")
        or "/store/" in rel
        or "/adapters/" in rel
        or rel.endswith(("schema.py", "errors.py", "config.py"))
    )


def _check_router_layer(
    imports: list[tuple[str, int]], tree: ast.Module, rel: str
) -> list[CodingViolation]:
    """Flag routers/entrypoints that directly access repositories or raw infrastructure."""
    violations: list[CodingViolation] = []
    seen: set[int] = set()
    for sym, lineno in imports:
        if lineno not in seen and any(
            sym == t or sym.endswith(f".{t}") for t in _ROUTER_FORBIDDEN_TARGETS
        ):
            seen.add(lineno)
            msg = f"[router-calls-repo-or-infra-directly] Router/Entrypoint '{rel}' directly imports '{sym}'."
            violations.append(
                CodingViolation("tier-separation-of-concerns", f"{rel}:{lineno}", msg)
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "deps"
            and node.attr in _DEPS_INFRA_ATTRS
            and node.lineno not in seen
        ):
            seen.add(node.lineno)
            msg = f"[router-calls-repo-or-infra-directly] Router '{rel}' accesses 'deps.{node.attr}' directly."
            violations.append(
                CodingViolation(
                    "tier-separation-of-concerns", f"{rel}:{node.lineno}", msg
                )
            )
    return violations


def _check_domain_and_low_tiers(
    imports: list[tuple[str, int]], rel: str
) -> list[CodingViolation]:
    """Check domain/agent modules bypassing adapters and low-tier upward imports."""
    violations: list[CodingViolation] = []
    seen: set[int] = set()
    if _is_domain_or_agent_module(rel):
        for sym, lineno in imports:
            if lineno not in seen and any(
                sym == t or sym.startswith(f"{t}.") for t in _DOMAIN_FORBIDDEN_INFRA
            ):
                seen.add(lineno)
                msg = f"[domain-bypasses-repo-or-adapter] Domain/Agent module '{rel}' directly imports '{sym}'."
                violations.append(
                    CodingViolation(
                        "tier-separation-of-concerns", f"{rel}:{lineno}", msg
                    )
                )
    if _is_low_tier_module(rel):
        for sym, lineno in imports:
            if any(part in sym.split(".") for part in _HIGHER_TIER_MARKERS):
                msg = f"[upward-layer-import] Lower-tier module '{rel}' imports higher-tier symbol '{sym}'."
                violations.append(
                    CodingViolation(
                        "tier-separation-of-concerns", f"{rel}:{lineno}", msg
                    )
                )
    return violations


def check_python_tier_isolation(source: str, rel_path: str) -> list[CodingViolation]:
    """Enforce cascaded and cross-cutting layer isolation across Python modules."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    rel = rel_path.replace("\\", "/")
    imports = _extract_py_imports(tree)
    violations: list[CodingViolation] = []
    if _is_router_or_entrypoint(rel):
        violations.extend(_check_router_layer(imports, tree, rel))
    violations.extend(_check_domain_and_low_tiers(imports, rel))
    return violations


def check_ts_tier_isolation(source: str, rel_path: str) -> list[CodingViolation]:
    """Enforce frontend component/store/API/DB separation of concerns."""
    clean = strip_ts_comments_preserve_lines(source)
    rel = rel_path.replace("\\", "/")
    violations: list[CodingViolation] = []
    is_ui_component = "/components/" in f"/{rel}" or "/app/" in f"/{rel}"

    for match in _TS_IMPORT_RE.finditer(clean):
        spec = match.group(1)
        lineno = clean[: match.start()].count("\n") + 1
        if any(
            spec == sdk or spec.startswith(f"{sdk}/") for sdk in _FORBIDDEN_TS_DB_SDKS
        ):
            msg = f"[frontend-direct-db-sdk] Frontend module '{rel}' imports DB/storage SDK '{spec}'."
            violations.append(
                CodingViolation("tier-separation-of-concerns", f"{rel}:{lineno}", msg)
            )
        elif is_ui_component and (
            spec == "@/lib/api"
            or spec.startswith("@/lib/api/")
            or spec.endswith("/serverAction")
        ):
            msg = f"[component-calls-api-or-db-directly] UI component '{rel}' imports API client '{spec}' directly."
            violations.append(
                CodingViolation("tier-separation-of-concerns", f"{rel}:{lineno}", msg)
            )
    return violations
