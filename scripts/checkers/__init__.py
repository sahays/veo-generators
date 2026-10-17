"""Modular coding standards checker package."""

from __future__ import annotations

from .brute_force import check_python_no_brute_force
from .folder_structure import check_folder_organization
from .logging_and_tests import (
    check_python_no_vanity_tests,
    check_python_semantic_logging,
    check_ts_semantic_logging,
)
from .models import (
    FRONTEND_SRC_DIR,
    MAX_FILE_STATEMENTS,
    MAX_FLAT_FILES_PER_DIR,
    MAX_FUNCTION_STATEMENTS,
    PYTHON_SCAN_DIRS,
    REPO_ROOT,
    CodingViolation,
)
from .owasp import check_python_owasp, check_ts_owasp_and_db_tier
from .size_and_types import (
    check_python_size_and_types,
    check_ts_size_and_types,
    count_py_non_comment_lines,
    count_py_statements,
)
from .tier_isolation import check_python_tier_isolation, check_ts_tier_isolation

__all__ = [
    "FRONTEND_SRC_DIR",
    "MAX_FILE_STATEMENTS",
    "MAX_FLAT_FILES_PER_DIR",
    "MAX_FUNCTION_STATEMENTS",
    "PYTHON_SCAN_DIRS",
    "REPO_ROOT",
    "CodingViolation",
    "check_folder_organization",
    "check_python_no_brute_force",
    "check_python_no_vanity_tests",
    "check_python_owasp",
    "check_python_semantic_logging",
    "check_python_size_and_types",
    "check_python_tier_isolation",
    "check_ts_owasp_and_db_tier",
    "check_ts_semantic_logging",
    "check_ts_size_and_types",
    "check_ts_tier_isolation",
    "count_py_non_comment_lines",
    "count_py_statements",
]
