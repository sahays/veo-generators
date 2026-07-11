"""Active picture area (baked letterbox/pillarbox bars) + the subject-aware
person picker — the two rf-yw9w9uk5 (Spider-Man trailer) failure classes.

1. A 2.39:1 scope trailer inside a 16:9 file wasted ~26% of every output frame
   on baked bars because nothing detected them (Step 2 of the 2026-07-11 plan).
2. The person fallback picked the LARGEST box per frame — an out-of-focus
   foreground guard's back — cropping Spider-Man (the story subject, left,
   with a face) fully out of frame (Step 3).
"""

import numpy as np
from reframe_active_area import (
    active_area_from_frames,
    crop_prefilter,
    outlier_shot_ranges,
    rect_px,
    slice_frame,
)
from reframe_filters import build_canvas_filter, build_split_filter
from reframe_signals import _person_groups, _segment_persons

# ---------------------------------------------------------------------------
# active_area_from_frames
# ---------------------------------------------------------------------------

H, W = 216, 384  # 16:9-ish, /8 of 4K


def _content(h=H, w=W, level=120):
    rng = np.random.default_rng(7)
    return rng.integers(40, 200, size=(h, w), dtype=np.uint8).clip(level - 80, 255)


def _letterboxed(bar=28):
    f = np.zeros((H, W), dtype=np.uint8)
    f[bar : H - bar, :] = _content(H - 2 * bar, W)
    return f


def test_full_frame_returns_none():
    assert active_area_from_frames([_content() for _ in range(4)]) is None


def test_letterbox_bars_detected():
    area = active_area_from_frames([_letterboxed() for _ in range(4)])
    assert area is not None
    assert abs(area["y0"] - 28 / H) < 0.01 and abs(area["y1"] - (H - 28) / H) < 0.01
    assert area["x0"] == 0.0 and area["x1"] == 1.0
    assert area["outliers"] == []


def test_pillarbox_bars_detected():
    f = np.zeros((H, W), dtype=np.uint8)
    f[:, 48 : W - 48] = _content(H, W - 96)
    area = active_area_from_frames([f for _ in range(4)])
    assert area is not None
    assert abs(area["x0"] - 48 / W) < 0.01 and abs(area["x1"] - (W - 48) / W) < 0.01


def test_minority_full_bleed_frame_tolerated_as_outlier():
    """The Spider-Man case: pure scope for 23/24 samples, full-bleed end slate.

    The rect must survive, with the disagreeing sample reported so its shot
    renders untrimmed."""
    frames = [_letterboxed() for _ in range(23)] + [_content()]
    area = active_area_from_frames(frames)
    assert area is not None
    assert abs(area["y0"] - 28 / H) < 0.01
    assert area["outliers"] == [23]


def test_mixed_format_source_not_trimmed():
    """Too many full-bleed samples = genuinely mixed formats → no trim."""
    frames = [_letterboxed() for _ in range(16)] + [_content() for _ in range(8)]
    assert active_area_from_frames(frames) is None


def test_subtitle_inside_bottom_bar_limits_trim():
    """Baked subtitles in the bar keep their rows (conservative: keep content)."""
    frames = []
    for _ in range(4):
        f = _letterboxed(bar=40)
        f[H - 20 : H - 12, 100:280] = 235  # bright subtitle inside bottom bar
        frames.append(f)
    area = active_area_from_frames(frames)
    assert area is not None
    assert abs(area["y0"] - 40 / H) < 0.01  # top bar fully trimmed
    assert area["y1"] > (H - 20) / H - 0.01  # bottom trim stops below the subtitle


def test_deep_dark_region_rejected_as_content():
    """A 'bar' deeper than MAX_BAR_FRAC is a dark scene, not padding."""
    f = np.zeros((H, W), dtype=np.uint8)
    f[int(H * 0.45) :, :] = _content(H - int(H * 0.45), W)  # top 45% dark
    assert active_area_from_frames([f for _ in range(4)]) is None


def test_hairline_bar_ignored():
    f = np.zeros((H, W), dtype=np.uint8)
    f[2 : H - 2, :] = _content(H - 4, W)  # sub-MIN_BAR_FRAC bars
    assert active_area_from_frames([f for _ in range(4)]) is None


# ---------------------------------------------------------------------------
# rect_px / crop_prefilter / slice_frame
# ---------------------------------------------------------------------------


def test_rect_px_even_and_full_frame_default():
    assert rect_px(None, 3840, 2160) == (0, 0, 3840, 2160)
    area = {"x0": 0.0, "y0": 276 / 2160, "x1": 1.0, "y1": 1884 / 2160}
    x, y, w, h = rect_px(area, 3840, 2160)
    assert (x, y, w, h) == (0, 276, 3840, 1608)
    assert w % 2 == 0 and h % 2 == 0 and y % 2 == 0


def test_crop_prefilter_string():
    assert crop_prefilter((0, 0, 3840, 2160), 3840, 2160) == ""
    assert crop_prefilter((0, 276, 3840, 1608), 3840, 2160) == "crop=3840:1608:0:276,"


def test_slice_frame_trims():
    f = np.arange(H * W, dtype=np.uint8).reshape(H, W)
    area = {"x0": 0.0, "y0": 0.25, "x1": 1.0, "y1": 0.75}
    out = slice_frame(f, area)
    assert out.shape[0] < H and out.shape[1] == W
    assert slice_frame(f, None) is f


def test_outlier_shot_ranges_maps_times_to_shots():
    area = {"x0": 0.0, "y0": 0.1, "x1": 1.0, "y1": 0.9, "outlier_times": [156.6]}
    ranges = outlier_shot_ranges(area, cuts=[10.0, 152.9], duration=161.6)
    assert ranges == [(152.9, 161.6)]
    assert outlier_shot_ranges(None, [10.0], 161.6) == []
    assert outlier_shot_ranges({**area, "outlier_times": []}, [10.0], 161.6) == []


# ---------------------------------------------------------------------------
# renderer: src_crop prefix
# ---------------------------------------------------------------------------


def test_canvas_filter_src_crop_prefix():
    kp = [(0.0, 0.5, 0.5)]
    base = build_canvas_filter(kp, 3840, 1608, (9, 16), 1080, 1920)
    pre = build_canvas_filter(
        kp, 3840, 1608, (9, 16), 1080, 1920, src_crop="crop=3840:1608:0:276,"
    )
    assert pre == base.replace("[0:v]", "[0:v]crop=3840:1608:0:276,")
    # default stays byte-identical to the pre-change filter shape
    assert "[0:v]crop=" not in base or base.startswith("[0:v]crop=904:1608")


def test_canvas_filter_letterboxed_bg_also_cropped():
    kp = [(0.0, 0.5, 0.5)]
    out = build_canvas_filter(
        kp, 3840, 1608, (16, 9), 1080, 1920, src_crop="crop=3840:1608:0:276,"
    )
    # both the blurred bg chain and the fg chain start from the trimmed source
    assert out.count("crop=3840:1608:0:276,") == 2


def test_split_filter_src_crop_prefix():
    kp = [(0.0, 0.3, 0.5)]
    out = build_split_filter(
        kp, kp, 3840, 1608, 1080, 1920, src_crop="crop=3840:1608:0:276,"
    )
    assert out.count("crop=3840:1608:0:276,") == 2


# ---------------------------------------------------------------------------
# subject-aware person picker (Step 3)
# ---------------------------------------------------------------------------
# The production case, scaled: Spider-Man (small, left-of-center, shows a tiny
# mask face) vs a guard's out-of-focus back (huge, right, never shows a face).


def _spidey_vs_guard_window(n=8):
    pf, tf = [], []
    for i in range(n):
        t = float(i)
        pf.append(
            {
                "time_sec": t,
                "persons": [
                    {"x": 0.81, "y": 0.5, "w": 0.38, "h": 0.9},  # guard's back
                    {"x": 0.37, "y": 0.6, "w": 0.16, "h": 0.5},  # Spider-Man
                ],
            }
        )
        tf.append(
            {
                "time_sec": t,
                # tiny mask face inside Spidey's box on most samples
                "tracks": [{"track_id": 1, "x": 0.36, "w": 0.04}] if i % 2 == 0 else [],
            }
        )
    return pf, tf


def test_legacy_pick_is_largest(monkeypatch):
    monkeypatch.setenv("REFRAME_PROMINENCE", "frac")
    pf, tf = _spidey_vs_guard_window()
    pts = _segment_persons(pf, tf, hint_x=0.5)
    assert all(p["x"] == 0.81 for p in pts)  # the failure this change removes


def test_subject_pick_prefers_face_and_bucket(monkeypatch):
    monkeypatch.delenv("REFRAME_PROMINENCE", raising=False)
    pf, tf = _spidey_vs_guard_window()
    pts = _segment_persons(pf, tf, hint_x=0.5)  # semantic: subject center
    assert pts and all(abs(p["x"] - 0.37) < 1e-6 for p in pts)


def test_face_evidence_alone_beats_size(monkeypatch):
    """No semantic hint: the person who ever shows a face still wins."""
    monkeypatch.delenv("REFRAME_PROMINENCE", raising=False)
    pf, tf = _spidey_vs_guard_window()
    pts = _segment_persons(pf, tf)
    assert pts and all(abs(p["x"] - 0.37) < 1e-6 for p in pts)


def test_no_evidence_falls_back_to_largest(monkeypatch):
    monkeypatch.delenv("REFRAME_PROMINENCE", raising=False)
    pf, _ = _spidey_vs_guard_window()
    tf = [{"time_sec": f["time_sec"], "tracks": []} for f in pf]
    pts = _segment_persons(pf, tf)
    assert pts and all(p["x"] == 0.81 for p in pts)


def test_series_follows_one_person_no_flicker(monkeypatch):
    """Alternating which person is biggest must not flicker the series."""
    monkeypatch.delenv("REFRAME_PROMINENCE", raising=False)
    pf = []
    for i in range(6):
        big_left = i % 2 == 0
        pf.append(
            {
                "time_sec": float(i),
                "persons": [
                    {"x": 0.3, "y": 0.5, "w": 0.30 if big_left else 0.20, "h": 0.8},
                    {"x": 0.7, "y": 0.5, "w": 0.20 if big_left else 0.30, "h": 0.8},
                ],
            }
        )
    tf = [{"time_sec": f["time_sec"], "tracks": []} for f in pf]
    pts = _segment_persons(pf, tf, hint_x=0.3)
    assert len({p["x"] for p in pts}) == 1  # one person, every frame


def test_person_groups_cluster_and_face_hits():
    pf, tf = _spidey_vs_guard_window()
    groups = _person_groups(pf, tf)
    assert len(groups) == 2
    spidey = min(groups, key=lambda g: g["lo"])
    guard = max(groups, key=lambda g: g["lo"])
    assert spidey["face"] and not guard["face"]
    assert guard["area"] > spidey["area"]
