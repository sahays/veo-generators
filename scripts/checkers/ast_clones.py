"""AST-based structural clone and size detectors for Python and TypeScript."""

from __future__ import annotations

import ast
import hashlib
import re

from .models import Violation

_TS_KEYWORDS: frozenset[str] = frozenset(
    {
        "const",
        "let",
        "var",
        "function",
        "return",
        "if",
        "else",
        "for",
        "while",
        "switch",
        "case",
        "break",
        "continue",
        "try",
        "catch",
        "finally",
        "throw",
        "new",
        "async",
        "await",
        "true",
        "false",
        "null",
        "undefined",
        "void",
        "typeof",
        "instanceof",
        "in",
        "of",
        "class",
        "extends",
        "super",
        "import",
        "export",
        "default",
        "from",
        "as",
    }
)
_TS_TOKEN_RE: re.Pattern[str] = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*|\d+(?:\.\d+)?|==|!=|<=|>=|=>|&&|\|\||[^\s]"
)
_TS_IDENT_RE: re.Pattern[str] = re.compile(r"^[a-z_$][A-Za-z0-9_$]*$")
_FUNC_DECL_RE: re.Pattern[str] = re.compile(
    r"(?:export\s+)?(?:const|function)\s+([A-Za-z0-9_]+)\s*(?:=\s*(?:async\s*)?(?:<[^>]+>\s*)?\([^)]*\)\s*(?::\s*[^=]+)?=>|\([^)]*\)\s*(?::\s*[^{]+)?\{)"
)


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

    def _strip_all_arg_annotations(self, args: ast.arguments) -> None:
        for arg in args.posonlyargs + args.args + args.kwonlyargs:
            arg.arg = self._norm_name(arg.arg)
            arg.annotation = None
        for varg in (args.vararg, args.kwarg):
            if varg is not None:
                varg.arg = self._norm_name(varg.arg)
                varg.annotation = None

    def _normalize_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        self._strip_all_arg_annotations(node.args)
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


def _count_ast_stmts(nodes: list[ast.stmt]) -> int:
    """Count non-docstring statements recursively inside an AST statement list."""
    total = 0
    for s in nodes:
        if (
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Constant)
            and isinstance(s.value.value, str)
        ):
            continue
        total += 1
        for attr in ("body", "orelse", "finalbody"):
            sub = getattr(s, attr, None)
            if isinstance(sub, list):
                total += _count_ast_stmts(sub)
        for h in getattr(s, "handlers", []):
            total += _count_ast_stmts(h.body)
    return total


def _hash_py_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return canonical SHA-256 digest for non-trivial Python functions, or None."""
    stmts = [
        s
        for s in node.body
        if not (
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Constant)
            and isinstance(s.value.value, str)
        )
    ]
    if len(stmts) < 6 or sum(1 for _ in ast.walk(node)) < 40:
        return None
    cloned = ast.parse(ast.unparse(node))
    norm_tree = _CanonicalASTNormalizer().visit(cloned)
    dump = ast.dump(norm_tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def _is_fn_limit_checked(rel: str) -> bool:
    """Return True if `rel` is a StoryGraph role/state module subject to AST statement limits."""
    return rel in (
        "productions_service/storygraph/agents/roles.py",
        "productions_service/storygraph/tools/role_helpers.py",
        "productions_service/storygraph/state.py",
    ) or rel.startswith(
        (
            "productions_service/storygraph/agents/role/",
            "productions_service/storygraph/tools/role_helpers/",
        )
    )


def check_py_clones_and_limits(
    tree: ast.Module, rel: str, seen_hashes: dict[str, tuple[str, str, int]]
) -> list[Violation]:
    """Check Python AST for duplicate functions and StoryGraph statement limits."""
    violations: list[Violation] = []
    if rel.startswith("productions_service/storygraph/"):
        file_stmts = _count_ast_stmts(tree.body)
        if file_stmts > 400:
            msg = f"File '{rel}' has {file_stmts} statements (max 400 per GEMINI.md)"
            violations.append(Violation("file-too-large", f"{rel}:1", msg))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_fn_limit_checked(rel):
            fn_stmts = _count_ast_stmts(node.body)
            if fn_stmts > 30:
                msg = f"Function '{node.name}' in {rel}:{node.lineno} has {fn_stmts} statements (max 30 per GEMINI.md)"
                violations.append(Violation("function-too-large", f"{rel}:{node.lineno}", msg))

        digest = _hash_py_function(node)
        if digest is None:
            continue
        if digest in seen_hashes:
            prev_rel, prev_name, prev_line = seen_hashes[digest]
            msg = f"Function '{node.name}' in {rel}:{node.lineno} is an AST clone of '{prev_name}' in {prev_rel}:{prev_line}"
            violations.append(Violation("duplicate-code", f"{rel}:{node.lineno}", msg))
        else:
            seen_hashes[digest] = (rel, node.name, node.lineno)
    return violations


def _step_ts_string(text: str, i: int, quote: str) -> tuple[int, str | None]:
    """Advance index `i` inside a quoted TypeScript string literal."""
    ch = text[i]
    if ch == "\\" and i + 1 < len(text):
        return i + 2, quote
    return i + 1, (None if ch == quote else quote)


def _extract_brace_block(text: str, start_idx: int) -> str | None:
    """Extract a balanced `{ ... }` or `=> ( ... )` body starting at `start_idx`."""
    idx = start_idx
    while idx < len(text) and text[idx] not in "{(":
        idx += 1
    if idx >= len(text):
        return None
    open_ch, close_ch = text[idx], ("}" if text[idx] == "{" else ")")
    depth, i, in_str = 0, idx, None
    while i < len(text):
        if in_str is not None:
            i, in_str = _step_ts_string(text, i, in_str)
            continue
        ch = text[i]
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
    tokens = _TS_TOKEN_RE.findall(code)
    var_map: dict[str, str] = {}
    norm: list[str] = []
    for idx, tok in enumerate(tokens):
        prev_tok = tokens[idx - 1] if idx > 0 else ""
        if (
            _TS_IDENT_RE.match(tok)
            and tok not in _TS_KEYWORDS
            and prev_tok not in (".", "<", "</")
        ):
            if tok not in var_map:
                var_map[tok] = f"$v{len(var_map)}"
            norm.append(var_map[tok])
        else:
            norm.append(tok)
    return tokens, " ".join(norm)


def check_ts_clones(
    raw: str,
    clean: str,
    rel_repo: str,
    seen_ts_blocks: dict[str, tuple[str, str, int]],
) -> list[Violation]:
    """Check a TypeScript file for duplicate function/component bodies."""
    violations: list[Violation] = []
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
                msg = (
                    f"Component/Function '{fn_name}' in {rel_repo}:{lineno} "
                    f"is a structural AST duplicate of '{prev_fn}' in {prev_file}:{prev_line}"
                )
                violations.append(Violation("duplicate-code", f"{rel_repo}:{lineno}", msg))
        else:
            seen_ts_blocks[digest] = (rel_repo, fn_name, lineno)
    return violations
