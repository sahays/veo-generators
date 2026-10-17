"""Folder organization checker banning flat file dumps and prefix-clustered sibling files."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .models import MAX_FLAT_FILES_PER_DIR, REPO_ROOT, CodingViolation

_SKIP_DIR_PARTS: tuple[str, ...] = (
    "venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".pytest_cache",
)
_TARGET_DIRS: tuple[str, ...] = (
    "api",
    "workers",
    "agents_service",
    "productions_service",
    "scripts",
    "frontend/src",
)
_MAX_PREFIX_CLUSTER: int = 4


def _should_skip_dir(path: Path) -> bool:
    """Return True if a directory belongs to build outputs, virtualenvs, or caches."""
    return any(part in _SKIP_DIR_PARTS for part in path.parts)


def _count_flat_sources(folder: Path) -> int:
    """Count direct `.py`, `.ts`, and `.tsx` source files inside `folder`."""
    return sum(
        1
        for f in folder.iterdir()
        if f.is_file() and f.suffix in (".py", ".ts", ".tsx") and f.name != "__init__.py"
    )


def _check_prefix_clusters(folder: Path, rel: str) -> list[CodingViolation]:
    """Flag non-test directories with >= 4 files sharing the same `<prefix>_*.py` prefix."""
    if rel.endswith("/tests") or "/tests/" in f"/{rel}/":
        return []
    clusters: dict[str, list[str]] = defaultdict(list)
    for f in sorted(folder.iterdir()):
        if not (f.is_file() and f.suffix == ".py" and "_" in f.stem):
            continue
        if f.name.startswith("_") or f.name.startswith("test_"):
            continue
        prefix = f.stem.split("_", 1)[0]
        if len(prefix) >= 3:
            clusters[prefix].append(f.name)

    violations: list[CodingViolation] = []
    for prefix, names in sorted(clusters.items()):
        if len(names) >= _MAX_PREFIX_CLUSTER:
            sample = ", ".join(names[:4])
            msg = (
                f"Directory '{rel}/' has {len(names)} `{prefix}_*.py` files ({sample}); "
                f"move them into `{rel}/{prefix}/*.py`."
            )
            violations.append(CodingViolation("folder-structure", f"{rel}/", msg))
    return violations


def check_folder_organization(
    root: Path = REPO_ROOT, max_flat_files: int = MAX_FLAT_FILES_PER_DIR
) -> list[CodingViolation]:
    """Flag directories that dump > `max_flat_files` files or cluster `>= 4` `<prefix>_*.py` files."""
    violations: list[CodingViolation] = []
    for rel_target in _TARGET_DIRS:
        base = root / rel_target
        if not base.exists():
            continue
        for folder in [base, *sorted(p for p in base.rglob("*") if p.is_dir())]:
            if _should_skip_dir(folder):
                continue
            rel = str(folder.relative_to(root)).replace("\\", "/")
            count = _count_flat_sources(folder)
            if count > max_flat_files:
                msg = f"Directory '{rel}/' contains {count} flat source files (max {max_flat_files}); organize into domain subfolders."
                violations.append(CodingViolation("folder-structure", f"{rel}/", msg))
            violations.extend(_check_prefix_clusters(folder, rel))
    return violations
