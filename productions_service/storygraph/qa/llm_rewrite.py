"""Optional cheap-LLM rewrite of unclassified critic reasons (`qa.retry_rewrite_llm`, default off).

Only used for free-text reasons that the deterministic keyword table cannot classify. The LLM
output is accepted only if it passes the same negative-vocabulary filter as the templates.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .retry_rewrite import BANNED_RE, ReasonRewriter, RewriteContext

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_PROMPT = (
    "Rewrite this video-QA failure into ONE short positive instruction describing the "
    "desired on-screen outcome for the next render. Describe only what should be seen. "
    "Use these names where relevant. Actors: {actors}. Props: {props}.\n"
    "Failure: {reason}"
)


class _Reviewer(Protocol):
    def review(self, images: list[bytes], prompt: str, schema: type[T]) -> T: ...


class _Rewrite(BaseModel):
    instruction: str = ""


def make_llm_rewriter(reviewer: _Reviewer) -> ReasonRewriter:
    """Wrap a VLM/LLM `review` provider as a `ReasonRewriter` that never raises."""

    def _rewrite(reason: str, ctx: RewriteContext) -> str | None:
        prompt = _PROMPT.format(
            actors=", ".join(ctx.actors) or "none listed",
            props=", ".join(p.name for p in ctx.props) or "none listed",
            reason=reason,
        )
        try:
            text = reviewer.review([], prompt, _Rewrite).instruction.strip()
        except Exception as exc:  # noqa: BLE001 - provider errors are untyped
            logger.warning(
                "LLM retry rewrite failed; using deterministic fallback",
                extra={
                    "who": "storygraph.qa.llm_rewrite",
                    "where": "make_llm_rewriter._rewrite",
                    "what": "retry_rewrite_llm_error",
                    "when": datetime.now(UTC).isoformat(),
                    "why": str(exc),
                    "how": "reviewer.review(schema=_Rewrite)",
                },
            )
            return None
        return text if text and not BANNED_RE.search(text) else None

    return _rewrite
