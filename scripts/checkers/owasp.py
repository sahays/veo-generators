"""OWASP Top 10 and Database Tier Isolation static checkers for Python and TypeScript."""

from __future__ import annotations

import ast
import re

from .models import CodingViolation, strip_ts_comments_preserve_lines

_FORBIDDEN_TS_DB_SDKS: tuple[str, ...] = (
    "@google-cloud/firestore",
    "@google-cloud/storage",
    "firebase-admin",
    "pg",
    "mongodb",
)

_TS_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:import|export)\s+(?:[^'\"\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

_TS_OWASP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bdangerouslySetInnerHTML\b"),
        "Disallowed `dangerouslySetInnerHTML` (OWASP A03 XSS risk).",
    ),
    (
        re.compile(r"\.innerHTML\s*="),
        "Disallowed `.innerHTML =` assignment (OWASP A03 XSS risk).",
    ),
    (
        re.compile(r"(?<![.\w])eval\s*\("),
        "Disallowed `eval()` execution (OWASP A03 Code Injection risk).",
    ),
)


def _check_py_call_owasp(node: ast.Call, rel_path: str) -> list[CodingViolation]:
    """Inspect a single Python `ast.Call` node for OWASP Top 10 anti-patterns."""
    found: list[CodingViolation] = []
    if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
        found.append(
            CodingViolation(
                "owasp-top-10",
                f"{rel_path}:{node.lineno}",
                f"Disallowed `{node.func.id}()` call (OWASP A03 Code Injection).",
            )
        )
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        mod, attr = node.func.value.id, node.func.attr
        if mod == "pickle" and attr in ("load", "loads"):
            found.append(
                CodingViolation(
                    "owasp-top-10",
                    f"{rel_path}:{node.lineno}",
                    "Disallowed `pickle.load/loads` (OWASP A08 Insecure Deserialization).",
                )
            )
        if mod == "yaml" and attr == "load" and not _has_safe_yaml_loader(node):
            found.append(
                CodingViolation(
                    "owasp-top-10",
                    f"{rel_path}:{node.lineno}",
                    "Disallowed `yaml.load()` without SafeLoader (use `yaml.safe_load`).",
                )
            )
    found.extend(_check_py_call_keywords(node, rel_path))
    return found


def _has_safe_yaml_loader(node: ast.Call) -> bool:
    """Return True if `yaml.load` specifies a `SafeLoader` positional or keyword arg."""
    if len(node.args) >= 2 and "SafeLoader" in ast.unparse(node.args[1]):
        return True
    return any(
        kw.arg == "Loader" and "SafeLoader" in ast.unparse(kw.value)
        for kw in node.keywords
    )


def _check_py_call_keywords(node: ast.Call, rel_path: str) -> list[CodingViolation]:
    """Check `shell=True` and `verify=False` keyword arguments on function calls."""
    found: list[CodingViolation] = []
    for kw in node.keywords:
        if (
            kw.arg == "shell"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
        ):
            found.append(
                CodingViolation(
                    "owasp-top-10",
                    f"{rel_path}:{node.lineno}",
                    "Disallowed `shell=True` in subprocess call (OWASP A03 Command Injection).",
                )
            )
        if (
            kw.arg == "verify"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
        ):
            found.append(
                CodingViolation(
                    "owasp-top-10",
                    f"{rel_path}:{node.lineno}",
                    "Disallowed `verify=False` TLS bypass (OWASP A02 Cryptographic Failures).",
                )
            )
    return found


def check_python_owasp(source: str, rel_path: str) -> list[CodingViolation]:
    """Scan Python source AST for OWASP Top 10 security violations."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    violations: list[CodingViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            violations.extend(_check_py_call_owasp(node, rel_path))
    return violations


def check_ts_owasp_and_db_tier(source: str, rel_path: str) -> list[CodingViolation]:
    """Scan TypeScript source for OWASP XSS/eval patterns and direct DB/Storage SDK imports."""
    clean = strip_ts_comments_preserve_lines(source)
    violations: list[CodingViolation] = []
    for pattern, msg in _TS_OWASP_PATTERNS:
        for match in pattern.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                CodingViolation("owasp-top-10", f"{rel_path}:{lineno}", msg)
            )
    for match in _TS_IMPORT_RE.finditer(clean):
        spec = match.group(1)
        if any(
            spec == sdk or spec.startswith(f"{sdk}/") for sdk in _FORBIDDEN_TS_DB_SDKS
        ):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                CodingViolation(
                    "tier-db-isolation",
                    f"{rel_path}:{lineno}",
                    f"Frontend file imports database/storage SDK '{spec}' directly; must call backend API.",
                )
            )
    return violations
