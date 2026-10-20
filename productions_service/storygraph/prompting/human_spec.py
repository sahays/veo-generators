"""Validate a human-authored Omni spec: strict `OmniClipSpec` schema + the S7 spec linter.

The spec is linted exactly as S7 lints compiled specs: against the shot's view, clip
context and (when present) the active spec of the previous clip in the same scene.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ..errors import NotFound
from ..lint.models import LintIssue, blocking
from ..lint.spec_lint import _case as lint_case  # shared S7 case builder
from ..lint.spec_lint import lint_spec
from ..omni.spec import OmniClipSpec
from ..repo import Repo
from ..repo.prompt_versions import PromptVersionRepo
from ..schema import Shot


class SpecRejected(ValueError):
    """Raised when a submitted spec fails schema validation or has blocking lint issues."""

    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__("; ".join(i["message"] for i in issues[:5]))


@dataclass(frozen=True)
class ValidatedSpec:
    """Canonical rendered spec JSON plus non-blocking lint warnings."""

    spec_json: str
    warnings: list[LintIssue]


def _parse(raw: str) -> OmniClipSpec:
    try:
        return OmniClipSpec.model_validate_json(raw)
    except ValidationError as exc:
        issues = [
            {
                "code": "SPEC_SCHEMA",
                "message": f"{'/'.join(map(str, e['loc']))}: {e['msg']}",
            }
            for e in exc.errors()
        ]
        raise SpecRejected(issues) from exc


def _prev_spec(repo: Repo, shot: Shot) -> OmniClipSpec | None:
    """Active spec of the previous clip in the scene (one shots query + one indexed get)."""
    before = [
        s
        for s in repo.list_shots(scene_id=shot.scene_id)
        if s.index_in_scene < shot.index_in_scene
    ]
    if not before:
        return None
    prev = max(before, key=lambda s: s.index_in_scene)
    active = PromptVersionRepo(repo.store).active_for_shot(prev.id)
    return OmniClipSpec.model_validate_json(active.spec_json) if active else None


def validate_human_spec(
    repo: Repo, shot_id: str, spec: str | dict[str, object]
) -> ValidatedSpec:
    """Return the canonical spec JSON or raise `SpecRejected` / `NotFound`."""
    shot = repo.get_shot(shot_id)
    if shot is None:
        raise NotFound(f"Shot {shot_id} not found")
    parsed = _parse(spec if isinstance(spec, str) else json.dumps(spec))
    issues = lint_spec(lint_case(repo, shot, parsed, _prev_spec(repo, shot)))
    errors = blocking(issues)
    if errors:
        raise SpecRejected([{"code": i.code, "message": i.message} for i in errors])
    warnings = [i for i in issues if i not in errors]
    return ValidatedSpec(parsed.render(), warnings)
