"""Domain error hierarchy for the Story-to-Video Graph system."""

from __future__ import annotations


class StoryGraphError(Exception):
    """Base error for all StoryGraph exceptions."""


class PermissionDenied(StoryGraphError):
    """Raised when a role attempts to mutate a node outside its ROLE_SCOPE."""


class ValidationFailed(StoryGraphError):
    """Raised when graph validation rules (V1-V13) fail with error severity."""

    def __init__(self, issues: list) -> None:
        self.issues = issues
        details = "; ".join(_describe_issue(i) for i in issues[:8])
        more = f" (+{len(issues) - 8} more)" if len(issues) > 8 else ""
        suffix = f": {details}{more}" if details else ""
        super().__init__(f"{len(issues)} validation error(s){suffix}")


def _describe_issue(issue: object) -> str:
    """Render an issue as `CODE node_id: message` (falls back to `str(issue)`)."""
    message = getattr(issue, "message", None)
    if message is None:
        return str(issue)
    code = getattr(issue, "code", "")
    node_id = getattr(issue, "node_id", "")
    head = " ".join(p for p in (code, node_id) if p)
    return f"{head}: {message}" if head else str(message)


class ShotsNotApproved(ValidationFailed):
    """Raised when final assembly is attempted while shots lack an APPROVED clip.

    `blocking` maps each blocking node id (usually a shot id) to its human-readable reasons.
    """

    def __init__(self, blocking: dict[str, list[str]], context: str = "") -> None:
        self.blocking = blocking
        super().__init__(
            [
                f"{node_id}: {'; '.join(reasons) or 'not approved'}"
                for node_id, reasons in blocking.items()
            ]
        )
        prefix = f"{context}: " if context else ""
        self.args = (
            f"{prefix}assembly blocked by {len(blocking)} unapproved item(s): "
            + ", ".join(blocking),
        )


class GateBlocked(StoryGraphError):
    """Raised when the pipeline reaches a human gate that is not yet approved."""

    def __init__(self, gate_id: str) -> None:
        self.gate_id = gate_id
        super().__init__(f"Gate {gate_id} is not approved")


class BudgetExceeded(StoryGraphError):
    """Raised when a stage or project exceeds configured token/retry/cost caps."""


class PromptTooLong(StoryGraphError):
    """Raised when a compiled shot prompt exceeds ProviderCaps.max_prompt_chars."""


class AlreadyExists(StoryGraphError):
    """Raised when attempting to overwrite an append-only node."""


class NotFound(StoryGraphError):
    """Raised when a requested node or blob does not exist."""


class DocTooLarge(StoryGraphError):
    """Raised when a serialized document exceeds the Firestore size guard."""


class StructuredOutputError(StoryGraphError):
    """Raised when an LLM agent fails to emit valid structured output after retries."""


def describe_exception(exc: BaseException) -> str:
    """Readable, never-empty `Type: message` (KeyError args unquoted; '(no message)' if blank)."""
    detail = (
        ", ".join(str(a) for a in exc.args) if isinstance(exc, KeyError) else str(exc)
    )
    return f"{type(exc).__name__}: {detail.strip() or '(no message)'}"


class ShotRepairError(StoryGraphError):
    """A repair/regenerate pass crashed on one shot; carries the shot id and root cause."""

    def __init__(self, shot_id: str, cause: BaseException) -> None:
        self.shot_id = shot_id
        self.cause = cause
        super().__init__(f"shot {shot_id}: {describe_exception(cause)}")
