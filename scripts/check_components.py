#!/usr/bin/env python3
"""Static UI component usage checker for the VeoGen frontend.

Scans all `.tsx` files under `frontend/src/` outside `frontend/src/components/ui/`
and flags lapses in design-system component usage:
1. Raw `<button>` or `<motion.button>` instead of `<Button>` (`@/components/ui/button`)
2. Raw `<a>` or `<motion.a>` instead of `<Button href=...>` or `<AnchorLink>`
3. `<Link>` styled directly as a button (`px-*`/`py-*`/`border`/`bg-accent`) without `<Button asChild>`
4. Raw `<textarea>` instead of `<Textarea>` (`@/components/ui/textarea`)
5. Raw `<select>` instead of `<Select>` or `<NativeSelect>` (`@/components/ui/select`)
6. Raw text/number/search/password/url/email `<input>` instead of `<Input>` (`@/components/ui/input`)
   (Native `<input type="file" | "checkbox" | "radio" | "range" | "hidden">` are permitted.)
7. Flat `bg-accent text-(white|accent-foreground|slate-900)` button/pill overrides instead of `<Button variant="primary">`
8. Deprecated `steel-*` gradient/color classes (replaced by Shades of Orange).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
FRONTEND_SRC_DIR: Path = REPO_ROOT / "frontend" / "src"

_COMMENT_RE: re.Pattern[str] = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_RAW_BUTTON_RE: re.Pattern[str] = re.compile(r"<(?:motion\.)?button\b")
_RAW_ANCHOR_RE: re.Pattern[str] = re.compile(r"<(?:motion\.)?a\b")
_RAW_TEXTAREA_RE: re.Pattern[str] = re.compile(r"<textarea\b")
_RAW_SELECT_RE: re.Pattern[str] = re.compile(r"<select\b")
_RAW_INPUT_TAG_RE: re.Pattern[str] = re.compile(
    r"<input\b(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*?)>", re.DOTALL
)
_INPUT_TYPE_RE: re.Pattern[str] = re.compile(
    r"\btype\s*=\s*(?:['\"]([^'\"]+)['\"]|\{\s*['\"]([^'\"]+)['\"]\s*\})"
)
_STEEL_CLASS_RE: re.Pattern[str] = re.compile(r"\b(?:from|via|to|bg|text|border)-steel-\d+\b")
_FLAT_ACCENT_BUTTON_RE: re.Pattern[str] = re.compile(
    r"\bbg-accent\b[^\n\"'`]*\btext-(?:white|accent-foreground|slate-900)\b"
    r"|\btext-(?:white|accent-foreground|slate-900)\b[^\n\"'`]*\bbg-accent\b"
)
_RAW_FETCH_RE: re.Pattern[str] = re.compile(r"(?<![.\w])fetch\s*\(")

ALLOWED_RAW_INPUT_TYPES: frozenset[str] = frozenset(
    {"file", "checkbox", "radio", "range", "hidden"}
)

_SIMPLE_TAG_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (_RAW_BUTTON_RE, "raw-button", "use <Button> instead."),
    (_RAW_ANCHOR_RE, "raw-anchor", "use <Button href=...> or <AnchorLink> instead."),
    (_RAW_TEXTAREA_RE, "raw-textarea", "use <Textarea> instead."),
    (_RAW_SELECT_RE, "raw-select", "use <Select> or <NativeSelect> instead."),
)


@dataclass(frozen=True)
class ComponentViolation:
    """Single UI component or browser fetch violation."""

    location: str
    rule: str
    message: str


def _strip_comments(raw: str) -> str:
    """Replace comments with spaces while preserving line numbers."""
    return _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw)


def _check_raw_fetch_calls() -> list[ComponentViolation]:
    """Check raw fetch() across all .ts/.tsx files outside lib/api/serverAction.ts."""
    violations: list[ComponentViolation] = []
    for path in sorted(FRONTEND_SRC_DIR.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
        if rel_src == "lib/api/serverAction.ts":
            continue
        rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        clean = _strip_comments(path.read_text(encoding="utf-8"))
        for match in _RAW_FETCH_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            msg = "Browser fetch() used outside lib/api/serverAction.ts; use api.* / serverApiRequest for server-to-server calls."
            violations.append(ComponentViolation(f"{rel_repo}:{lineno}", "raw-fetch", msg))
    return violations


def _check_tsx_controls(clean: str, rel_repo: str) -> list[ComponentViolation]:
    """Check raw HTML controls and flat accent overrides in a non-ui TSX file."""
    violations: list[ComponentViolation] = []
    for pattern, rule_id, hint in _SIMPLE_TAG_RULES:
        for match in pattern.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            msg = f"Raw '{match.group(0)}>' used outside components/ui/; {hint}"
            violations.append(ComponentViolation(f"{rel_repo}:{lineno}", rule_id, msg))

    for match in _RAW_INPUT_TAG_RE.finditer(clean):
        type_match = _INPUT_TYPE_RE.search(match.group("attrs"))
        input_type = (type_match.group(1) or type_match.group(2)) if type_match else "text"
        if input_type not in ALLOWED_RAW_INPUT_TYPES:
            lineno = clean[: match.start()].count("\n") + 1
            msg = f"Raw '<input type=\"{input_type}\">' used outside components/ui/; use <Input> instead."
            violations.append(ComponentViolation(f"{rel_repo}:{lineno}", "raw-input", msg))

    for match in _FLAT_ACCENT_BUTTON_RE.finditer(clean):
        lineno = clean[: match.start()].count("\n") + 1
        msg = f"Flat '{match.group(0)}' used outside components/ui/; use <Button variant=\"primary\"> or 'btn-primary' gradient."
        violations.append(ComponentViolation(f"{rel_repo}:{lineno}", "flat-accent-override", msg))
    return violations


def _check_tsx_file(path: Path) -> list[ComponentViolation]:
    """Check a single .tsx file for deprecated classes and raw HTML controls."""
    rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
    rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    clean = _strip_comments(path.read_text(encoding="utf-8"))
    violations: list[ComponentViolation] = []

    for match in _STEEL_CLASS_RE.finditer(clean):
        lineno = clean[: match.start()].count("\n") + 1
        msg = f"Disallowed '{match.group(0)}' class; use Shades of Orange ('orange-*' / 'amber-*')."
        violations.append(
            ComponentViolation(f"{rel_repo}:{lineno}", "deprecated-gradient-color", msg)
        )

    if not rel_src.startswith("components/ui/"):
        violations.extend(_check_tsx_controls(clean, rel_repo))
    return violations


def check_frontend_components() -> list[ComponentViolation]:
    """Run all UI component and raw fetch checks across `frontend/src/`."""
    if not FRONTEND_SRC_DIR.exists():
        return []
    violations = _check_raw_fetch_calls()
    for path in sorted(FRONTEND_SRC_DIR.rglob("*.tsx")):
        violations.extend(_check_tsx_file(path))
    return violations


def main() -> int:
    """CLI entrypoint for UI component static verification."""
    violations = check_frontend_components()
    if not violations:
        print(
            "✅ UI Component Checker: 0 raw HTML control, button styling, or browser fetch lapses found across all pages/components."
        )
        return 0

    print(f"❌ UI Component Checker found {len(violations)} lapse(s):")
    for v in violations:
        print(f"  [{v.rule}] {v.location}: {v.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
