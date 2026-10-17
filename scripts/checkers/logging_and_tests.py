"""Semantic logging (5W1H) and anti-vanity-test static analyzers."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import CodingViolation

_LOG_METHODS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical"}
)
_TS_CONSOLE_RE = re.compile(r"\bconsole\.(log|warn|error|info|debug)\s*\(")


def _is_production_py(rel_path: str) -> bool:
    """Return True if `rel_path` is a production service Python file (not test or CLI script)."""
    if rel_path.startswith("scripts/") or "/tests/" in f"/{rel_path}":
        return False
    name = Path(rel_path).name
    return not (name.startswith("test_") or name == "conftest.py")


def _is_test_py(rel_path: str) -> bool:
    """Return True if `rel_path` is a Python test module."""
    name = Path(rel_path).name
    return "/tests/" in f"/{rel_path}" or name.startswith("test_")


def _has_semantic_context(call: ast.Call) -> bool:
    """Check whether a logger call includes structured 5W1H context (`extra=` or multi-field kv)."""
    if any(kw.arg == "extra" for kw in call.keywords):
        return True
    if not call.args:
        return False
    first_arg = call.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return len(call.args) >= 3 and "=" in first_arg.value
    if isinstance(first_arg, ast.JoinedStr):
        formatted_count = sum(1 for v in first_arg.values if isinstance(v, ast.FormattedValue))
        has_kv = any(
            isinstance(v, ast.Constant) and isinstance(v.value, str) and "=" in v.value
            for v in first_arg.values
        )
        return formatted_count >= 3 and has_kv
    return False


def _check_py_call_logging(node: ast.Call, rel_path: str) -> CodingViolation | None:
    """Inspect a single AST Call node for raw `print()` or non-semantic logger calls."""
    if isinstance(node.func, ast.Name) and node.func.id == "print":
        return CodingViolation(
            rule="semantic-logging",
            location=f"{rel_path}:{node.lineno}",
            message="Raw `print()` in service code; use structured semantic logging (Who/Where/What/When/Why/How).",
        )
    if isinstance(node.func, ast.Attribute) and node.func.attr in _LOG_METHODS:
        if not _has_semantic_context(node):
            return CodingViolation(
                rule="semantic-logging",
                location=f"{rel_path}:{node.lineno}",
                message=f"Logger call `.{node.func.attr}()` lacks structured 5W1H context (`extra={{...}}` or key=value fields).",
            )
    return None


def check_python_semantic_logging(source: str, rel_path: str) -> list[CodingViolation]:
    """Enforce semantic 5W1H logging in Python production modules."""
    if not _is_production_py(rel_path):
        return []
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    violations: list[CodingViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            violation = _check_py_call_logging(node, rel_path)
            if violation is not None:
                violations.append(violation)
    return violations


def check_ts_semantic_logging(source: str, rel_path: str) -> list[CodingViolation]:
    """Flag raw `console.log/warn/error/info/debug` calls lacking structured semantic telemetry."""
    violations: list[CodingViolation] = []
    in_block = False
    for idx, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if in_block:
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            continue
        match = _TS_CONSOLE_RE.search(stripped)
        if match:
            violations.append(
                CodingViolation(
                    rule="semantic-logging",
                    location=f"{rel_path}:{idx}",
                    message=f"Raw `console.{match.group(1)}()` lacks structured 5W1H semantic logging context.",
                )
            )
    return violations


def _is_trivial_assert(test_expr: ast.expr) -> bool:
    """Return True if an assert expression only checks `assert True`, `is not None`, or `isinstance`."""
    if isinstance(test_expr, (ast.Constant, ast.Name)):
        return True
    if (
        isinstance(test_expr, ast.Call)
        and isinstance(test_expr.func, ast.Name)
        and test_expr.func.id in ("isinstance", "hasattr", "callable", "bool")
    ):
        return True
    if isinstance(test_expr, ast.Compare) and len(test_expr.ops) == 1:
        op = test_expr.ops[0]
        right = test_expr.comparators[0]
        if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return True
    return False


def _has_meaningful_verification(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, bool]:
    """Return `(has_any_check, has_non_trivial_check)` for a test function AST node."""
    assert_nodes = [n for n in ast.walk(fn_node) if isinstance(n, ast.Assert)]
    has_helper_check = False
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Attribute) and (
            node.attr == "raises"
            or node.attr.startswith("assert")
        ):
            has_helper_check = True
            break
    has_any = bool(assert_nodes) or has_helper_check
    has_strong = has_helper_check or any(not _is_trivial_assert(a.test) for a in assert_nodes)
    return has_any, has_strong


def check_python_no_vanity_tests(source: str, rel_path: str) -> list[CodingViolation]:
    """Detect vanity tests (zero assertions or only superficial existence/type checks)."""
    if not _is_test_py(rel_path):
        return []
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    violations: list[CodingViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            has_any, has_strong = _has_meaningful_verification(node)
            if not has_any:
                violations.append(
                    CodingViolation(
                        rule="no-vanity-tests",
                        location=f"{rel_path}:{node.lineno}",
                        message=f"Vanity test `{node.name}` has zero assertions or exception checks.",
                    )
                )
            elif not has_strong:
                violations.append(
                    CodingViolation(
                        rule="no-vanity-tests",
                        location=f"{rel_path}:{node.lineno}",
                        message=f"Vanity test `{node.name}` only asserts `is not None`/`isinstance`/truthiness without behavioral checks.",
                    )
                )
    return violations
