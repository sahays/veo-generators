"""AST detector for brute-force O(N) lookups inside loops."""

from __future__ import annotations

import ast

from .models import CodingViolation


def _find_index_calls_in_loop(
    loop_node: ast.For | ast.While, rel_path: str
) -> list[CodingViolation]:
    """Flag `.index(...)` linear scans inside a `for` or `while` loop."""
    violations: list[CodingViolation] = []
    for sub in ast.walk(loop_node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "index"
        ):
            violations.append(
                CodingViolation(
                    rule="no-brute-force",
                    location=f"{rel_path}:{sub.lineno}",
                    message="Linear `.index()` inside loop causes O(N^2) complexity; precompute an index dict or use enumerate().",
                )
            )
    return violations


def _find_nested_list_membership(
    outer_loop: ast.For | ast.While, rel_path: str
) -> list[CodingViolation]:
    """Flag `x in [...]` against constant list/tuple literals (>=5 items) inside nested loops."""
    violations: list[CodingViolation] = []
    for child in ast.iter_child_nodes(outer_loop):
        for sub in ast.walk(child):
            if isinstance(sub, (ast.For, ast.While)):
                violations.extend(_check_inner_loop_comparisons(sub, rel_path))
    return violations


def _check_inner_loop_comparisons(
    inner_loop: ast.For | ast.While, rel_path: str
) -> list[CodingViolation]:
    """Inspect comparisons inside an inner loop for large constant list/tuple membership."""
    found: list[CodingViolation] = []
    for node in ast.walk(inner_loop):
        if not isinstance(node, ast.Compare):
            continue
        for op, comp in zip(node.ops, node.comparators):
            if (
                isinstance(op, (ast.In, ast.NotIn))
                and isinstance(comp, (ast.List, ast.Tuple))
                and len(comp.elts) >= 5
                and all(isinstance(elt, ast.Constant) for elt in comp.elts)
            ):
                found.append(
                    CodingViolation(
                        rule="no-brute-force",
                        location=f"{rel_path}:{node.lineno}",
                        message="Membership check against >=5 element list/tuple inside nested loop; hoist to a `set`/`frozenset` for O(1) lookup.",
                    )
                )
    return found


def check_python_no_brute_force(source: str, rel_path: str) -> list[CodingViolation]:
    """Check Python AST for `.index()` in loops and repeated list membership in nested loops."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    seen: set[tuple[str, str]] = set()
    results: list[CodingViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            for v in _find_index_calls_in_loop(node, rel_path) + _find_nested_list_membership(
                node, rel_path
            ):
                key = (v.location, v.message)
                if key not in seen:
                    seen.add(key)
                    results.append(v)
    return results
