"""Shared models and constants for coding standard and architecture checkers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC_DIR: Path = REPO_ROOT / "frontend" / "src"

PYTHON_SCAN_DIRS: tuple[str, ...] = (
    "api",
    "workers",
    "agents_service",
    "productions_service",
    "scripts",
)

MAX_FILE_STATEMENTS: int = 400
MAX_FUNCTION_STATEMENTS: int = 30
MAX_FLAT_FILES_PER_DIR: int = 15

TS_COMMENT_RE: re.Pattern[str] = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")


@dataclass(frozen=True)
class CodingViolation:
    """Single coding standard violation reported by a static checker."""

    rule: str
    location: str
    message: str


@dataclass(frozen=True)
class Violation:
    """Single architecture or AST duplication violation."""

    category: str
    location: str
    message: str


def strip_ts_comments_preserve_lines(source: str) -> str:
    """Replace TS/JS comments with spaces while keeping line numbers intact."""
    return TS_COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)
