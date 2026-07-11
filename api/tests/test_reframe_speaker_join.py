"""Speaker join (Phase 5): audio WHO (Chirp) × semantic WHERE × MAR validation.

Pins the join order (MAR overrides semantic position), the offscreen
suppression that kills the voiceover-poster hijack class, the single-face
speech pin, and the adversarial cases (chewing outside speech must not pin;
the equal-two-shot product rule still outranks speaker-centering).
"""

from reframe_plan import reconcile
from reframe_semantic import reconcile_semantics, validate
from reframe_signals import _norm_speaker, _semantic_speaker_position

SRC_W, SRC_H = 1920, 1080
SPEECH = [{"speaker_id": "1", "start_sec": 0.0, "end_sec": 6.0}]


def _frame(t, tracks):
    return {"time_sec": t, "tracks": tracks}


def _tr(tid, x, w=0.1, mouth=None):
    t = {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": 0.9}
    if mouth is not None:
        t["mouth"] = mouth
    return t


def _scenes(kind, speakers):
    shots = validate(
        {
            "shots": [
                {
                    "start_sec": 0,
                    "end_sec": 6,
                    "content_kind": kind,
                    "speakers": speakers,
                }
            ]
        },
        [],
        6.0,
    )
    return reconcile_semantics(shots, None)


def _talking(t, i):
    """Oscillating MAR — a talking mouth."""
    return 0.2 if i % 2 == 0 else 0.6


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------
def test_speaker_label_normalization():
    assert _norm_speaker("Speaker 1") == _norm_speaker("S1") == _norm_speaker(1)
    scene = {"speakers": [{"speaker_id": "Speaker 2", "position": "right"}]}
    assert _semantic_speaker_position(scene, "2") == "right"
    assert _semantic_speaker_position(scene, "1") is None
    assert _semantic_speaker_position(scene, None) is None


# ---------------------------------------------------------------------------
# Join order
# ---------------------------------------------------------------------------
def test_semantic_position_snaps_when_mar_is_silent():
    # Two faces, speech, no usable mouth signal — the semantic pass says the
    # speaker is on the LEFT → pin the left track. (Pre-join this escalated a
    # static-thumbnail "who is talking?" question Gemini can't actually see.)
    scenes = _scenes("talking_head", [{"speaker_id": "1", "position": "left"}])
    tracked = [_frame(t, [_tr(1, 0.25, w=0.12), _tr(2, 0.75, w=0.2)]) for t in range(7)]
    plan = reconcile(
        scenes,
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=SPEECH,
    )
    crop = plan[0]["crops"][0]
    assert crop["source"] == "speaker"
    assert crop["track_id"] == 1


def test_mar_overrides_semantic_position():
    # The RIGHT face is visibly talking during speech; the semantic pass
    # (shot-level, coarse) says left. Frame-accurate MAR wins.
    scenes = _scenes("talking_head", [{"speaker_id": "1", "position": "left"}])
    tracked = [
        _frame(
            t,
            [
                _tr(1, 0.25, w=0.2, mouth=0.3),
                _tr(2, 0.75, w=0.12, mouth=_talking(t, t)),
            ],
        )
        for t in range(7)
    ]
    plan = reconcile(
        scenes,
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=SPEECH,
    )
    crop = plan[0]["crops"][0]
    assert crop["source"] == "speaker"
    assert crop["track_id"] == 2


def test_offscreen_narrator_suppresses_speaker_centering():
    # Voiceover over footage showing a non-talking person: the poster-hijack
    # class. No speaker pin, no active_speaker escalation — plain face framing.
    scenes = _scenes("talking_head", [{"speaker_id": "1", "position": "offscreen"}])
    tracked = [
        _frame(t, [_tr(1, 0.3, w=0.2, mouth=0.3), _tr(2, 0.7, w=0.1, mouth=0.31)])
        for t in range(7)
    ]
    plan = reconcile(
        scenes,
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=SPEECH,
    )
    crop = plan[0]["crops"][0]
    assert crop["source"] != "speaker"
    esc = plan[0].get("escalate") or {}
    assert esc.get("kind") != "active_speaker"


def test_single_face_speech_pin():
    # One face whose mouth oscillates during diarized speech → deterministic
    # speaker pin (source="speaker"). Structurally impossible before Phase 1:
    # MAR was only computed when ≥2 faces co-occurred in one 1fps sample.
    tracked = [_frame(t, [_tr(1, 0.4, w=0.15, mouth=_talking(t, t))]) for t in range(7)]
    plan = reconcile(
        [],
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=SPEECH,
    )
    assert plan[0]["crops"][0]["source"] == "speaker"


# ---------------------------------------------------------------------------
# Adversarial + product rule
# ---------------------------------------------------------------------------
def test_chewing_outside_speech_does_not_pin():
    # Face 2's mouth moves a lot — but only OUTSIDE the diarized speech span.
    # Speech-gated MAR must not count it; with nothing else to go on the pick
    # falls back to plain subject framing, not a speaker pin on the chewer.
    speech = [{"speaker_id": "1", "start_sec": 0.0, "end_sec": 3.0}]
    tracked = [
        _frame(
            t,
            [
                _tr(1, 0.3, w=0.2, mouth=0.3),
                _tr(2, 0.7, w=0.1, mouth=(_talking(t, t) if t > 3 else 0.3)),
            ],
        )
        for t in range(7)
    ]
    plan = reconcile(
        [],
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=speech,
    )
    for seg in plan:
        crop = seg["crops"][0]
        assert not (crop.get("source") == "speaker" and crop.get("track_id") == 2)


def test_equal_two_shot_still_outranks_speaker_centering():
    # Two equally prominent people, one clearly speaking: frame BOTH (the
    # rf-udcpl2hd product rule) — the speak_mult boost must not demote the
    # silent equal partner out of the group.
    tracked = [
        _frame(
            t,
            [
                _tr(1, 0.3, w=0.15, mouth=_talking(t, t)),
                _tr(2, 0.7, w=0.15, mouth=0.3),
            ],
        )
        for t in range(7)
    ]
    plan = reconcile(
        [],
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        speaker_segments=SPEECH,
    )
    assert plan[0]["layout"] in ("keep_both", "split")
