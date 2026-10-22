"""Semantic (5W1H) log context shared by the voiceover package."""

from __future__ import annotations

from datetime import UTC, datetime


def log_ctx(
    where: str, what: str, why: str, how: str, **fields: object
) -> dict[str, object]:
    """`extra=` payload answering who/where/what/when/why/how plus structured fields."""
    return {
        "who": "storygraph.audio.voice",
        "where": where,
        "what": what,
        "when": datetime.now(UTC).isoformat(),
        "why": why,
        "how": how,
        **fields,
    }
