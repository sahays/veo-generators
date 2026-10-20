"""Text hygiene for Omni prompts: ID resolution, null filtering, punctuation, identity condensing."""

from __future__ import annotations

import re
from typing import Final

from ..clips.species import own_sentences
from ..clips.text import strip_timestamps
from ..timeline.placement import cut_phrase

_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(obj|char|loc|prop|ast|shot|scn|evt|app|dlg|comp)_[A-Za-z0-9_]+\b"
)
_HUMANIZE_PREFIXES: Final[frozenset[str]] = frozenset({"obj", "char", "loc", "prop"})
_SNAKE_RE: Final[re.Pattern[str]] = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_NULLISH: Final[frozenset[str]] = frozenset(
    {"", "none", "null", "nil", "n/a", "na", "undefined", "unknown", "-"}
)
_NULL_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:wearing|holding|with)\s+(?:none|null|n/a)\b[,;]?", re.IGNORECASE
)
_ELLIPSIS_RE: Final[re.Pattern[str]] = re.compile(r"\.{3}")
_MULTI_DOT_RE: Final[re.Pattern[str]] = re.compile(r"\.{2,}")
_PUNCT_RUN_RE: Final[re.Pattern[str]] = re.compile(r"([,;:])\s*([,;:.])")
_DOT_COMMA_RE: Final[re.Pattern[str]] = re.compile(r"\.\s*([,;])")
_SPACE_BEFORE_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"\s+([,.;:!?])")
_EMPTY_PARENS_RE: Final[re.Pattern[str]] = re.compile(r"\(\s*\)")
_SPACES_RE: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
_STYLE_PHRASE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:rendered|animated|painted|drawn|illustrated|designed|outlined|framed|depicted|styled)"
    r"\s+(?:in|with|by|using)\b[^,.;]*",
    re.IGNORECASE,
)
_STYLE_NOUN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:gouache|watercolou?rs?|linework|line art|line work|cel|cel-shaded|"
    r"brushstrokes?|aesthetic|art style|painterly|cgi)\b",
    re.IGNORECASE,
)
_SENTENCE_END: Final[str] = ".!?\u2026\"'"
_REPEAT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([A-Za-z][\w'-]*)(?:\s+\1\b)+", re.IGNORECASE
)


class IdResolver:
    """Replace raw graph IDs with canonical names; unknown entity IDs are humanized, others dropped."""

    def __init__(self, names: dict[str, str]) -> None:
        self._names = names

    def _sub(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        if raw in self._names:
            return self._names[raw]
        if match.group(1) in _HUMANIZE_PREFIXES:
            return raw.split("_", 1)[1].replace("_", " ")
        return ""

    def __call__(self, text: str) -> str:
        resolved = _ID_RE.sub(self._sub, text)
        return _SNAKE_RE.sub(lambda m: m.group(0).replace("_", " "), resolved)


def is_blank(value: str | None) -> bool:
    return value is None or value.strip().lower() in _NULLISH


def tidy(text: str) -> str:
    """Collapse whitespace and broken punctuation ('..', '.,', ' ,', '()')."""
    out = _ELLIPSIS_RE.sub("\u2026", text)
    out = _MULTI_DOT_RE.sub(".", out)
    out = _DOT_COMMA_RE.sub(".", out)
    out = _PUNCT_RUN_RE.sub(r"\2", out)
    out = _EMPTY_PARENS_RE.sub("", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    return _SPACES_RE.sub(" ", out).strip(" ,;:")


def clean(text: str | None, resolver: IdResolver) -> str:
    """Resolve IDs, drop null tokens and timestamps, tidy punctuation; '' for null-ish input."""
    if is_blank(text):
        return ""
    out = _NULL_WORD_RE.sub("", resolver(str(text)))
    out = tidy(strip_timestamps(out))
    return "" if is_blank(out) else out


def sentence(text: str) -> str:
    """Return `text` as one sentence ending in exactly one terminal mark ('' stays '')."""
    body = tidy(text)
    if not body:
        return ""
    return body if body[-1] in _SENTENCE_END else f"{body}."


def _strip_style(text: str) -> str:
    """Remove per-entity style restatements (the SHOT header owns the style)."""
    out = _STYLE_PHRASE_RE.sub("", text)
    clauses = [c for c in out.split(",") if c.strip() and not _STYLE_NOUN_RE.search(c)]
    body = tidy(",".join(clauses))
    return body[:1].upper() + body[1:] if body else ""


def _cap_chars(text: str, limit: int) -> str:
    return text if len(text) <= limit else sentence(cut_phrase(text, limit))


def collapse_repeats(text: str) -> str:
    """'Pip Pip reaches' -> 'Pip reaches' (case-insensitive adjacent duplicate words)."""
    return _REPEAT_RE.sub(lambda m: m.group(1), text)


def has_repeats(text: str) -> bool:
    return bool(_REPEAT_RE.search(text))


def strip_actor_lead(text: str, actor: str) -> str:
    """'Pip pushes the chair' -> 'pushes the chair' when `actor` is Pip (possessive kept)."""
    if not actor.strip():
        return text
    lead = re.match(
        rf"\s*{re.escape(actor.strip())}\b(?!['\u2019]s)[\s,]*", text, re.IGNORECASE
    )
    if lead is None or lead.end() >= len(text):
        return text
    return text[lead.end() :]


def condense_identity(
    description: str | None,
    resolver: IdResolver,
    other_names: list[str],
    max_sentences: int,
    max_chars: int = 260,
) -> str:
    """Condense a free description to its identity essentials (own sentences, no style, capped)."""
    if max_sentences <= 0:
        return ""
    text = clean(description, resolver)
    kept = [s for s in (_strip_style(x) for x in own_sentences(text, other_names)) if s]
    if (
        not kept
    ):  # every sentence names someone else: keep the first one (identity floor)
        kept = [s for s in (_strip_style(x) for x in own_sentences(text, [])) if s][:1]
    body = " ".join(sentence(s) for s in kept[:max_sentences])
    if not re.search(r"[A-Za-z]", body):  # style-only text: keep the raw first sentence
        body = first_sentence(text, resolver)
    return _cap_chars(body, max_chars)


def first_sentence(text: str | None, resolver: IdResolver, max_chars: int = 160) -> str:
    """First sentence of `text`, cleaned and capped (used for the style header)."""
    cleaned = clean(text, resolver)
    head = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0] if cleaned else ""
    return _cap_chars(head.rstrip("."), max_chars).rstrip(".")


def humanize(value: str) -> str:
    """'formal_suit' -> 'formal suit'."""
    return value.replace("_", " ").strip()
