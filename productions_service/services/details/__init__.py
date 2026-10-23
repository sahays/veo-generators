"""Lazy detail endpoints (run attempts, audit log pages, scene detail) for the studio UI."""

from .audit_page import AUDIT_PAGE_DEFAULT, AUDIT_PAGE_MAX
from .service import audit_log_page, scene_detail, shot_run_history

__all__ = [
    "AUDIT_PAGE_DEFAULT",
    "AUDIT_PAGE_MAX",
    "audit_log_page",
    "scene_detail",
    "shot_run_history",
]
