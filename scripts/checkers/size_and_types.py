"""File/function size limits and strict typing checkers for Python and TypeScript."""

from __future__ import annotations

import ast
import re

from .models import (
    MAX_FILE_STATEMENTS,
    MAX_FUNCTION_STATEMENTS,
    CodingViolation,
    strip_ts_comments_preserve_lines,
)

_PY_TRIPLE_QUOTE_RE: re.Pattern[str] = re.compile(
    r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\''
)
_TS_EXPLICIT_ANY_RE: re.Pattern[str] = re.compile(
    r":\s*any\b|\bas\s+any\b|<\s*any\s*>|,\s*any\s*>"
)
_TS_STMT_LINE_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:import|export|const|let|var|function|return|if|else\s+if|for|while|switch|case|try|catch|throw)\b|;\s*$|<[A-Za-z]",
    re.MULTILINE,
)
_TS_FUNC_START_RE: re.Pattern[str] = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{|"
    r"(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?(?:<[^>]+>\s*)?\([^)]*\)\s*(?::\s*[^=]+)?=>\s*\{"
)


def _is_docstring_expr(stmt: ast.stmt) -> bool:
    """Return True if an AST statement is a string literal docstring."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def count_py_statements(nodes: list[ast.stmt]) -> int:
    """Recursively count non-docstring AST statements inside a block."""
    total = 0
    for stmt in nodes:
        if _is_docstring_expr(stmt):
            continue
        total += 1
        for attr in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, attr, None)
            if isinstance(sub, list):
                total += count_py_statements(sub)
        for handler in getattr(stmt, "handlers", []):
            total += count_py_statements(handler.body)
    return total


def count_py_non_comment_lines(source_segment: str) -> int:
    """Count non-empty, non-comment, non-docstring lines in a Python snippet."""
    no_docs = _PY_TRIPLE_QUOTE_RE.sub("", source_segment)
    return sum(
        1
        for raw_line in no_docs.splitlines()
        if raw_line.strip() and not raw_line.strip().startswith("#")
    )


def _py_function_size(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    enforce_strict_body: bool,
) -> int:
    """Compute recursive AST statement count of a Python function body (excluding docstrings)."""
    body_without_doc = [s for s in node.body if not _is_docstring_expr(s)]
    if not body_without_doc:
        return 0
    return (
        count_py_statements(body_without_doc)
        if enforce_strict_body
        else len(body_without_doc)
    )


def _check_py_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    enforce_strict_body: bool,
) -> list[CodingViolation]:
    """Check a single Python function's statement count and type annotations."""
    violations: list[CodingViolation] = []
    stmt_count = _py_function_size(node, enforce_strict_body)
    if stmt_count > MAX_FUNCTION_STATEMENTS:
        violations.append(
            CodingViolation(
                "function-size-limit",
                f"{rel_path}:{node.lineno}",
                f"Function '{node.name}' has {stmt_count} statements (max {MAX_FUNCTION_STATEMENTS}).",
            )
        )
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg:
        args.append(node.args.vararg)
    if node.args.kwarg:
        args.append(node.args.kwarg)
    untyped = [
        a.arg for a in args if a.arg not in ("self", "cls") and a.annotation is None
    ]
    if untyped or node.returns is None:
        violations.append(
            CodingViolation(
                "strict-typing",
                f"{rel_path}:{node.lineno}",
                f"Function '{node.name}' is missing type annotations (untyped params: {untyped}, return annotated: {node.returns is not None}).",
            )
        )
    return violations


def check_python_size_and_types(
    source: str, rel_path: str, enforce_strict_body: bool = True
) -> list[CodingViolation]:
    """Check Python file size (<=400), function size (<=30), and strict typing."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    violations: list[CodingViolation] = []
    ast_file_stmts = count_py_statements(tree.body)
    code_lines = count_py_non_comment_lines(source)
    file_size = (
        max(ast_file_stmts, code_lines) if enforce_strict_body else ast_file_stmts
    )
    if file_size > MAX_FILE_STATEMENTS:
        violations.append(
            CodingViolation(
                "file-size-limit",
                f"{rel_path}:1",
                f"File '{rel_path}' has {file_size} non-comment lines/statements (max {MAX_FILE_STATEMENTS}).",
            )
        )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_check_py_function(node, rel_path, enforce_strict_body))
    return violations


def _count_ts_code_lines(clean_segment: str) -> int:
    """Count non-empty, non-comment code lines plus semicolon statements in TypeScript."""
    non_empty = sum(1 for ln in clean_segment.splitlines() if ln.strip())
    semi_stmts = sum(1 for _ in _TS_STMT_LINE_RE.finditer(clean_segment))
    return max(non_empty, semi_stmts)


def _extract_ts_brace_block(clean: str, open_brace_idx: int) -> str:
    """Return the balanced `{ ... }` substring starting at `open_brace_idx`."""
    depth = 0
    for idx in range(open_brace_idx, len(clean)):
        if clean[idx] == "{":
            depth += 1
        elif clean[idx] == "}":
            depth -= 1
            if depth == 0:
                return clean[open_brace_idx : idx + 1]
    return clean[open_brace_idx:]


def _check_ts_functions(clean: str, rel_path: str) -> list[CodingViolation]:
    """Check all TypeScript function/component declarations for statement/line limits."""
    violations: list[CodingViolation] = []
    for match in _TS_FUNC_START_RE.finditer(clean):
        fn_name = match.group(1) or match.group(2) or "anonymous"
        lineno = clean[: match.start()].count("\n") + 1
        block = _extract_ts_brace_block(clean, match.end() - 1)
        fn_stmts = _count_ts_code_lines(block) - 2
        if fn_stmts > MAX_FUNCTION_STATEMENTS:
            violations.append(
                CodingViolation(
                    "function-size-limit",
                    f"{rel_path}:{lineno}",
                    f"TypeScript function/component '{fn_name}' has {fn_stmts} non-comment lines/statements (max {MAX_FUNCTION_STATEMENTS}).",
                )
            )
    return violations


def check_ts_size_and_types(
    source: str, rel_path: str, enforce_no_any: bool = True
) -> list[CodingViolation]:
    """Check TypeScript file/function statement limits and ban explicit `any` types."""
    clean = strip_ts_comments_preserve_lines(source)
    violations: list[CodingViolation] = []
    stmt_count = _count_ts_code_lines(clean)
    if stmt_count > MAX_FILE_STATEMENTS:
        violations.append(
            CodingViolation(
                "file-size-limit",
                f"{rel_path}:1",
                f"TypeScript file '{rel_path}' has {stmt_count} non-comment lines/statements (max {MAX_FILE_STATEMENTS}).",
            )
        )
    violations.extend(_check_ts_functions(clean, rel_path))
    if enforce_no_any:
        for match in _TS_EXPLICIT_ANY_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                CodingViolation(
                    "strict-typing",
                    f"{rel_path}:{lineno}",
                    f"Disallowed explicit `any` ('{match.group(0).strip()}'); use structured types or `unknown`.",
                )
            )
    return violations
