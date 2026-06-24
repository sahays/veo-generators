"""Strongly-typed reframe plan — the central artifact, with an EXPLAIN printer.

Like a query planner's plan: a video's reframe decision is a typed, time-ordered
sequence of `Segment` nodes, each naming a chosen `Layout` operator, the rung it
crops to, the facts that drove it, and — when the CPU couldn't decide — the
`Escalation` it raised to gemini-3.5-flash (with a deterministic fallback).

Dicts live only at the Firestore boundary: `ReframePlan.from_dict` parses a
stored record into this model and `to_dict` serializes back. In between, code
reasons over enums and frozen dataclasses (no stringly-typed key access), and
`ReframePlan.explain()` prints the whole plan so you can see, for any video, what
the planner decided and why.

This module is pure (no I/O); the planner (`reframe_plan`) will be migrated to
build it natively. For now it adapts the planner's existing dict output.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class Layout(str, Enum):
    SINGLE = "single"  # one crop follows one subject
    KEEP_BOTH = "keep_both"  # one crop wide enough to hold two faces
    SPLIT = "split"  # two stacked full-canvas panels


class CropSource(str, Enum):
    FACE = "face"
    SPEAKER = "speaker"  # active-speaker face (mouth movement)
    PERSON = "person"  # body fallback (no stable face)
    CENTER = "center"  # no detection / Gemini spatial hint
    SPLIT_TOP = "split_top"
    SPLIT_BOTTOM = "split_bottom"
    UNKNOWN = "unknown"


class EscalationKind(str, Enum):
    TEXT_PRESENCE = "text_presence"
    SUBJECT_CHOICE = "subject_choice"
    ACTIVE_SPEAKER = "active_speaker"
    KEEP_BOTH = "keep_both"
    SPLIT = "split"
    NO_SUBJECT = "no_subject"
    PERSON_WIDEN = "person_widen"


class DecisionStatus(str, Enum):
    RESOLVED = "resolved"  # deterministic and confident
    ESCALATED = "escalated"  # awaiting a gemini-3.5-flash verdict


# The full-bleed (tightest) rung per canvas — a segment at this rung fills the
# portrait canvas with no bars; any looser rung letterboxes. NOTE: low source-
# width coverage (e.g. 9:16 keeps 0.32 of width) is the *tight* full-bleed crop;
# full coverage (16:9 keeps 1.0) is the *most* letterboxed — the inverse of cov.
CANVAS_TIGHTEST: dict = {"9:16": (9, 16), "3:4": (3, 4)}


def _enum(cls, value, default):
    """Tolerant enum coercion — unknown stored strings degrade to `default`."""
    try:
        return cls(value)
    except (ValueError, KeyError):
        return default


@dataclass(frozen=True)
class Crop:
    source: CropSource
    x_target: float
    track_id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Crop":
        return cls(
            source=_enum(CropSource, d.get("source"), CropSource.UNKNOWN),
            x_target=float(d.get("x_target", 0.5)),
            track_id=d.get("track_id"),
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "x_target": self.x_target,
            "track_id": self.track_id,
        }


@dataclass(frozen=True)
class Escalation:
    """A judgment the CPU deferred to gemini-3.5-flash, with its fallback."""

    kind: EscalationKind
    key: str
    question: str
    facts: dict
    fallback: dict

    @classmethod
    def from_dict(cls, d: dict) -> "Escalation":
        return cls(
            kind=_enum(EscalationKind, d.get("kind"), EscalationKind.NO_SUBJECT),
            key=d.get("key", ""),
            question=d.get("question", ""),
            facts=d.get("facts", {}),
            fallback=d.get("fallback", {}),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "key": self.key,
            "question": self.question,
            "facts": self.facts,
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class Segment:
    """One reframe decision node over [start, end)."""

    index: int
    start: float
    end: float
    layout: Layout
    inner_ar: Optional[Tuple[int, int]]  # None for SPLIT (panels fill canvas)
    source: CropSource
    reason: str
    coverage: float  # fraction of source width the rung keeps (1.0 = full-bleed)
    n_faces: int
    n_persons: int
    c_measured: float
    c_text: float
    letterboxed: bool
    crops: Tuple[Crop, ...]
    escalation: Optional[Escalation]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def status(self) -> DecisionStatus:
        return DecisionStatus.ESCALATED if self.escalation else DecisionStatus.RESOLVED

    @property
    def rung_label(self) -> str:
        if self.inner_ar is None:
            return "split"
        return f"{self.inner_ar[0]}:{self.inner_ar[1]}"

    @classmethod
    def from_dict(cls, d: dict, index: int, canvas: str = "9:16") -> "Segment":
        trace = d.get("trace") or {}
        ar = d.get("inner_ar")
        inner_ar = tuple(ar) if ar else None
        crops = tuple(Crop.from_dict(c) for c in (d.get("crops") or []))
        esc = d.get("escalate")
        layout = _enum(Layout, d.get("layout"), Layout.SINGLE)
        tightest = CANVAS_TIGHTEST.get(canvas, (9, 16))
        letterboxed = (
            layout is not Layout.SPLIT and inner_ar is not None and inner_ar != tightest
        )
        return cls(
            index=index,
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            layout=layout,
            inner_ar=inner_ar,
            source=_enum(CropSource, trace.get("source"), CropSource.UNKNOWN),
            reason=d.get("reason") or trace.get("trigger", ""),
            coverage=float(trace.get("coverage", 1.0)),
            n_faces=int(trace.get("n_faces", 0)),
            n_persons=int(trace.get("n_persons", 0)),
            c_measured=float(trace.get("c_measured", 0.0)),
            c_text=float(trace.get("c_text", 0.0)),
            letterboxed=letterboxed,
            crops=crops,
            escalation=Escalation.from_dict(esc) if esc else None,
        )

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "layout": self.layout.value,
            "inner_ar": list(self.inner_ar) if self.inner_ar else None,
            "source": self.source.value,
            "reason": self.reason,
            "coverage": round(self.coverage, 3),
            "n_faces": self.n_faces,
            "n_persons": self.n_persons,
            "crops": [c.to_dict() for c in self.crops],
            "escalate": self.escalation.to_dict() if self.escalation else None,
        }


def _mmss(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


@dataclass(frozen=True)
class ReframePlan:
    src_w: int
    src_h: int
    duration: float
    canvas: str
    segments: Tuple[Segment, ...]
    plan_id: Optional[str] = None

    # ---- construction ----------------------------------------------------
    @classmethod
    def from_dict(
        cls,
        record: dict,
        src_w: Optional[int] = None,
        src_h: Optional[int] = None,
    ) -> "ReframePlan":
        """Parse a stored reframe record (its `segment_plan`) into the model.

        Source dims are read from `eval_report.meta` when present; pass `src_w`/
        `src_h` to override or when the record predates that metadata.
        """
        segs_raw = record.get("segment_plan") or []
        meta = (record.get("eval_report") or {}).get("meta") or {}
        sw = src_w or meta.get("src_w")
        sh = src_h or meta.get("src_h")
        if not sw or not sh:
            raise ValueError(
                "source dims unavailable — pass src_w/src_h "
                "(not in eval_report.meta for this record)"
            )
        canvas = record.get("output_aspect_ratio") or "9:16"
        segments = tuple(
            Segment.from_dict(s, i, canvas) for i, s in enumerate(segs_raw)
        )
        duration = max((s.end for s in segments), default=0.0)
        return cls(
            src_w=int(sw),
            src_h=int(sh),
            duration=duration,
            canvas=canvas,
            segments=segments,
            plan_id=record.get("id"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.plan_id,
            "src_w": self.src_w,
            "src_h": self.src_h,
            "duration": self.duration,
            "canvas": self.canvas,
            "segments": [s.to_dict() for s in self.segments],
        }

    # ---- derived views ---------------------------------------------------
    @property
    def escalated(self) -> List[Segment]:
        return [s for s in self.segments if s.escalation]

    def _escalation_points(self) -> List[dict]:
        from reframe_escalation import make_point

        pts = []
        for s in self.escalated:
            e = s.escalation
            pts.append(
                make_point(
                    kind=e.kind.value,
                    key=e.key,
                    question=e.question,
                    facts=e.facts,
                    fallback=e.fallback,
                    start=s.start,
                    end=s.end,
                )
            )
        return pts

    def batch_plan(self) -> dict:
        from reframe_escalation import plan_batches

        return plan_batches(self._escalation_points())

    # ---- EXPLAIN ---------------------------------------------------------
    def explain(self) -> str:
        from reframe_escalation import DECISION_MODEL, summarize

        lb = sum(1 for s in self.segments if s.letterboxed)
        lines = [
            f"ReframePlan {self.plan_id or '(unsaved)'}  "
            f"{self.src_w}x{self.src_h} → {self.canvas}  "
            f"{self.duration:.1f}s  {len(self.segments)} segments  ({lb} letterboxed)",
        ]
        src_hist = Counter(s.source.value for s in self.segments)
        rung_hist = Counter(s.rung_label for s in self.segments)
        lines.append(
            "  sources: " + " · ".join(f"{v} {k}" for k, v in src_hist.items())
        )
        lines.append(
            "  rungs:   " + " · ".join(f"{v}×{k}" for k, v in rung_hist.items())
        )
        if self.escalated:
            lines.append("  " + summarize(self.batch_plan()))
        else:
            lines.append(f"  escalations: none ({DECISION_MODEL} not needed)")
        lines.append("  " + "─" * 76)
        lines.append(
            f"  {'#':>3}  {'time':<13} {'layout':<9} {'rung':<6} {'cov':>4}  flags  why"
        )
        for s in self.segments:
            flags = ("L" if s.letterboxed else " ") + ("E" if s.escalation else " ")
            lines.append(
                f"  {s.index:>3}  {_mmss(s.start)}-{_mmss(s.end):<7} "
                f"{s.layout.value:<9} {s.rung_label:<6} {s.coverage:>4.2f}  "
                f" {flags}    {s.reason}"
            )
        for s in self.escalated:
            e = s.escalation
            lines.append(
                f"  ⚡ [{e.kind.value}] {_mmss(s.start)}-{_mmss(s.end)}  "
                f"{e.question}  → fallback: {e.fallback.get('action', '?')}"
            )
        return "\n".join(lines)
