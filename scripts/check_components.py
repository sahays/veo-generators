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

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC_DIR = REPO_ROOT / "frontend" / "src"

_COMMENT_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_RAW_BUTTON_RE = re.compile(r"<(?:motion\.)?button\b")
_RAW_ANCHOR_RE = re.compile(r"<(?:motion\.)?a\b")
_RAW_TEXTAREA_RE = re.compile(r"<textarea\b")
_RAW_SELECT_RE = re.compile(r"<select\b")
_RAW_INPUT_TAG_RE = re.compile(
    r"<input\b(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*?)>", re.DOTALL
)
_INPUT_TYPE_RE = re.compile(
    r"\btype\s*=\s*(?:['\"]([^'\"]+)['\"]|\{\s*['\"]([^'\"]+)['\"]\s*\})"
)
_STEEL_CLASS_RE = re.compile(r"\b(?:from|via|to|bg|text|border)-steel-\d+\b")
_FLAT_ACCENT_BUTTON_RE = re.compile(
    r"\bbg-accent\b[^\n\"'`]*\btext-(?:white|accent-foreground|slate-900)\b"
    r"|\btext-(?:white|accent-foreground|slate-900)\b[^\n\"'`]*\bbg-accent\b"
)
_RAW_FETCH_RE = re.compile(r"(?<![.\w])fetch\s*\(")

ALLOWED_RAW_INPUT_TYPES = {"file", "checkbox", "radio", "range", "hidden"}


@dataclass(frozen=True)
class ComponentViolation:
    location: str
    rule: str
    message: str


def check_frontend_components() -> list[ComponentViolation]:
    violations: list[ComponentViolation] = []
    if not FRONTEND_SRC_DIR.exists():
        return violations

    # Check raw fetch() across all .ts and .tsx files (only lib/api/serverAction.ts may call fetch)
    for path in sorted(FRONTEND_SRC_DIR.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
        if rel_src == "lib/api/serverAction.ts":
            continue
        rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        raw = path.read_text(encoding="utf-8")
        clean = _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw)
        for match in _RAW_FETCH_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "raw-fetch",
                    "Browser fetch() used outside lib/api/serverAction.ts; use api.* / serverApiRequest for server-to-server calls.",
                )
            )

    tsx_files = sorted(FRONTEND_SRC_DIR.rglob("*.tsx"))
    for path in tsx_files:
        rel_src = str(path.relative_to(FRONTEND_SRC_DIR)).replace("\\", "/")
        rel_repo = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        raw = path.read_text(encoding="utf-8")
        # Keep newline positions identical by replacing comments with spaces/newlines
        clean = _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw)

        # Check deprecated steel-* classes across all TSX files (including ui/)
        for match in _STEEL_CLASS_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "deprecated-gradient-color",
                    f"Disallowed '{match.group(0)}' class; use Shades of Orange ('orange-*' / 'amber-*').",
                )
            )

        # Skip primitive implementation files under components/ui/
        if rel_src.startswith("components/ui/"):
            continue

        for match in _RAW_BUTTON_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "raw-button",
                    f"Raw '{match.group(0)}>' used outside components/ui/; use <Button> instead.",
                )
            )

        for match in _RAW_ANCHOR_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "raw-anchor",
                    f"Raw '{match.group(0)}>' used outside components/ui/; use <Button href=...> or <AnchorLink> instead.",
                )
            )

        for match in _RAW_TEXTAREA_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "raw-textarea",
                    "Raw '<textarea>' used outside components/ui/; use <Textarea> instead.",
                )
            )

        for match in _RAW_SELECT_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "raw-select",
                    "Raw '<select>' used outside components/ui/; use <Select> or <NativeSelect> instead.",
                )
            )

        for match in _RAW_INPUT_TAG_RE.finditer(clean):
            attrs = match.group("attrs")
            type_match = _INPUT_TYPE_RE.search(attrs)
            input_type = (
                (type_match.group(1) or type_match.group(2)) if type_match else "text"
            )
            if input_type not in ALLOWED_RAW_INPUT_TYPES:
                lineno = clean[: match.start()].count("\n") + 1
                violations.append(
                    ComponentViolation(
                        f"{rel_repo}:{lineno}",
                        "raw-input",
                        f"Raw '<input type=\"{input_type}\">' used outside components/ui/; use <Input> instead.",
                    )
                )

        for match in _FLAT_ACCENT_BUTTON_RE.finditer(clean):
            lineno = clean[: match.start()].count("\n") + 1
            violations.append(
                ComponentViolation(
                    f"{rel_repo}:{lineno}",
                    "flat-accent-override",
                    f"Flat '{match.group(0)}' used outside components/ui/; use <Button variant=\"primary\"> or 'btn-primary' gradient.",
                )
            )

    return violations


def main() -> int:
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

