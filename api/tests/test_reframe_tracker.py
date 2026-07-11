"""Tracker v2 + detector-merge behaviors (Phase 1 perception fixes).

Pins the exact failure modes that starved the planner: one missed detection
minting a new track_id, identities leaking across scene cuts, and the same face
double-counted when two BlazeFace variants both see it.
"""

from mediapipe_detection import _hist_dist, _iou, _merge_nms, track_faces


def _face(x, y=0.5, w=0.12, h=0.2, conf=0.9, hist=None):
    f = {"x": x, "y": y, "w": w, "h": h, "confidence": conf}
    if hist is not None:
        f["hist"] = hist
    return f


def _frames(rows):
    """rows: list of (t, [face,...]) → frames_data."""
    return [{"time_sec": t, "faces": faces} for t, faces in rows]


def _ids(result):
    return [[tr["track_id"] for tr in fr["tracks"]] for fr in result]


# ---------------------------------------------------------------------------
# v2: gap tolerance
# ---------------------------------------------------------------------------
def test_track_survives_missed_sample():
    # Face at t=0, missing at t=0.25 (detector blink), back at t=0.5 → same id.
    # This is THE v1 failure: every blink minted a new identity, fragmenting a
    # subject into shards that all failed the planner's STABLE_FRAC gate.
    frames = _frames(
        [
            (0.0, [_face(0.5)]),
            (0.25, []),
            (0.5, [_face(0.51)]),
        ]
    )
    ids = _ids(track_faces(frames))
    assert ids == [[0], [], [0]]


def test_track_retires_after_gap():
    # Gone for well over _GAP_SEC → the re-appearance is a new identity.
    frames = _frames(
        [(0.0, [_face(0.5)])]
        + [(0.25 * i, []) for i in range(1, 10)]
        + [(2.5, [_face(0.5)])]
    )
    ids = _ids(track_faces(frames))
    assert ids[0] == [0]
    assert ids[-1] == [1]


# ---------------------------------------------------------------------------
# v2: cut reset
# ---------------------------------------------------------------------------
def test_identity_never_crosses_a_cut():
    # Same position before and after a scene cut = a DIFFERENT person in a new
    # shot (shot-reverse-shot dialogue). v1 leaked the id across.
    frames = _frames(
        [
            (0.0, [_face(0.5)]),
            (0.25, [_face(0.5)]),
            (0.5, [_face(0.5)]),
            (0.75, [_face(0.5)]),
        ]
    )
    ids = _ids(track_faces(frames, cuts=[0.4]))
    assert ids[0] == [0] and ids[1] == [0]
    assert ids[2] == [1] and ids[3] == [1]


def test_gap_does_not_bridge_a_cut():
    # A track in flight when the cut lands must not re-link after it.
    frames = _frames(
        [
            (0.0, [_face(0.5)]),
            (0.25, []),
            (0.5, [_face(0.5)]),
        ]
    )
    ids = _ids(track_faces(frames, cuts=[0.3]))
    assert ids == [[0], [], [1]]


# ---------------------------------------------------------------------------
# v2: motion ceiling + appearance
# ---------------------------------------------------------------------------
def test_big_jump_is_a_new_identity():
    # Half a frame-width in one 0.25s sample is far beyond the per-sample
    # motion ceiling (0.5 frame-widths/sec) → different subject.
    frames = _frames(
        [
            (0.0, [_face(0.2)]),
            (0.25, [_face(0.8)]),
        ]
    )
    ids = _ids(track_faces(frames))
    assert ids == [[0], [1]]


def test_two_faces_keep_distinct_ids():
    frames = _frames(
        [
            (0.0, [_face(0.3), _face(0.7)]),
            (0.25, [_face(0.31), _face(0.69)]),
            (0.5, [_face(0.32), _face(0.68)]),
        ]
    )
    ids = _ids(track_faces(frames))
    assert ids[0] == [0, 1]
    assert ids[1] == [0, 1]
    assert ids[2] == [0, 1]


def test_hist_dist_identity_and_disjoint():
    a = [0.5, 0.5, 0.0, 0.0]
    b = [0.0, 0.0, 0.5, 0.5]
    assert _hist_dist(a, a) < 1e-6
    assert _hist_dist(a, b) > 0.99


# ---------------------------------------------------------------------------
# v1 fallback flag
# ---------------------------------------------------------------------------
def test_v1_flag_restores_legacy_behavior(monkeypatch):
    monkeypatch.setenv("REFRAME_TRACKER", "v1")
    # v1 has no gap tolerance: the blink mints a new id.
    frames = _frames(
        [
            (0.0, [_face(0.5)]),
            (1.0, []),
            (2.0, [_face(0.5)]),
        ]
    )
    ids = _ids(track_faces(frames))
    assert ids == [[0], [], [1]]


# ---------------------------------------------------------------------------
# detector variant merge
# ---------------------------------------------------------------------------
def test_nms_merges_same_face_across_variants():
    short = _face(0.50, w=0.20, h=0.30, conf=0.9)
    full = _face(0.51, w=0.21, h=0.31, conf=0.7)
    assert _iou(short, full) > 0.5
    merged = _merge_nms([short, full])
    assert merged == [short]  # higher confidence wins


def test_nms_keeps_distinct_faces():
    a = _face(0.25, w=0.1, h=0.2, conf=0.9)
    b = _face(0.75, w=0.1, h=0.2, conf=0.8)
    assert _merge_nms([a, b]) == [a, b]
