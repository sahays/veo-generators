"""Tests for the dubbing timeline assembly and config guards.

No network, no credentials, no ffmpeg: `dubbing_timeline` is deliberately pure
so the alignment maths — the part that decides whether a dub is watchable — can
be pinned down exactly.
"""

import array
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "workers"))

import dubbing_config  # noqa: E402
from base_processor import resolve_variant_status  # noqa: E402
from dubbing_timeline import (  # noqa: E402
    assemble_track,
    build_srt,
    is_silent,
    measure_lag,
)

RATE = 24000
WIDTH = 2
BPS = RATE * WIDTH  # bytes per second of 24 kHz mono s16le


def tone(seconds: float, value: int = 8000) -> bytes:
    """Non-silent PCM of a given length."""
    n = int(seconds * RATE)
    return array.array("h", [value] * n).tobytes()


def first_nonzero_byte(pcm: bytes) -> int:
    for i, b in enumerate(pcm):
        if b:
            return i
    return -1


def _to_seconds(timecode: str) -> float:
    hms, ms = timecode.split(",")
    h, m, s = (int(p) for p in hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms) / 1000


def _parse_spans(srt: str) -> list[tuple[float, float]]:
    """(start, end) of every cue, read back out of rendered SRT."""
    return [
        (_to_seconds(a), _to_seconds(b))
        for a, b in re.findall(
            r"(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)", srt
        )
    ]


class TestMeasureLag:
    def test_lag_is_output_minus_onset(self):
        assert measure_lag(3.4, 0.5) == pytest.approx(2.9)

    def test_output_before_onset_clamps_to_zero(self):
        # A silence probe fooled by music under the intro must not shift the
        # track the wrong way.
        assert measure_lag(1.0, 4.0) == 0.0

    def test_no_output_means_no_shift(self):
        assert measure_lag(None, 4.0) == 0.0


class TestAssembleTrack:
    def test_track_length_is_exactly_the_video_duration(self):
        # The mux relies on this: any drift here becomes A/V desync.
        out = assemble_track([(0.0, tone(1.0))], 0.0, 10.0, RATE)
        assert len(out) == int(10.0 * RATE) * WIDTH

    def test_chunk_lands_at_its_stamp(self):
        out = assemble_track([(2.0, tone(0.5))], 0.0, 5.0, RATE)
        assert first_nonzero_byte(out) == 2 * BPS

    def test_lag_shifts_the_chunk_earlier(self):
        out = assemble_track([(3.4, tone(0.5))], 3.4, 5.0, RATE)
        assert first_nonzero_byte(out) == 0

    def test_stamp_earlier_than_lag_clamps_to_zero(self):
        out = assemble_track([(1.0, tone(0.5))], 3.4, 5.0, RATE)
        assert first_nonzero_byte(out) == 0

    def test_overlapping_chunks_append_instead_of_truncating(self):
        # The interpreter emits faster than the stamps advance, so many chunks
        # share a stamp. All of their audio must survive.
        chunks = [(1.0, tone(0.4, 5000)) for _ in range(3)]
        out = assemble_track(chunks, 0.0, 10.0, RATE)
        voiced = sum(1 for s in array.array("h", out) if s != 0)
        assert voiced == int(0.4 * RATE) * 3

    def test_contiguous_speech_stays_contiguous(self):
        # Same stamp, three chunks: no silence gets inserted between them.
        out = assemble_track([(0.0, tone(0.2))] * 3, 0.0, 5.0, RATE)
        samples = array.array("h", out)
        run = int(0.6 * RATE)
        assert all(s != 0 for s in samples[:run])
        assert all(s == 0 for s in samples[run:])

    def test_offsets_stay_sample_aligned(self):
        # An odd byte offset would split a 16-bit sample and turn the rest of
        # the track into noise. 3/48000 s is 1.5 samples in: rounding to whole
        # frames gives byte 2, while scaling straight to bytes would give the
        # odd byte 3. Asserting the exact offset makes the test discriminating
        # rather than trivially true.
        out = assemble_track([(3 / 48000, tone(0.1))], 0.0, 1.0, RATE)
        assert first_nonzero_byte(out) == 2

    def test_audio_past_the_end_is_dropped_not_appended(self):
        out = assemble_track([(4.5, tone(3.0))], 0.0, 5.0, RATE)
        assert len(out) == int(5.0 * RATE) * WIDTH

    def test_chunk_stamped_beyond_duration_is_skipped(self):
        out = assemble_track([(9.0, tone(1.0))], 0.0, 5.0, RATE)
        assert first_nonzero_byte(out) == -1

    def test_empty_chunks_are_ignored(self):
        out = assemble_track([(1.0, b""), (2.0, tone(0.1))], 0.0, 5.0, RATE)
        assert first_nonzero_byte(out) == 2 * BPS

    def test_zero_duration_returns_empty(self):
        assert assemble_track([(0.0, tone(1.0))], 0.0, 0.0, RATE) == b""


class TestIsSilent:
    def test_digital_silence_is_silent(self):
        assert is_silent(b"\x00" * 4800, -60.0)

    def test_speech_level_audio_is_not_silent(self):
        assert not is_silent(tone(0.1), -60.0)

    def test_empty_chunk_is_silent(self):
        assert is_silent(b"", -60.0)

    def test_very_low_level_noise_counts_as_silent(self):
        # Keep-alive audio is not always bit-exact zero.
        assert is_silent(array.array("h", [2] * 2400).tobytes(), -60.0)


class TestBuildSrt:
    def test_cue_runs_until_the_next_one(self):
        srt = build_srt([(0.0, "uno"), (4.0, "dos")], 0.0, 10.0)
        assert "00:00:00,000 --> 00:00:04,000" in srt
        assert "00:00:04,000 --> 00:00:10,000" in srt

    def test_lag_shift_applies_to_cues(self):
        srt = build_srt([(3.4, "hola")], 3.4, 10.0)
        assert srt.startswith("1\n00:00:00,000 --> ")

    def test_blank_fragments_are_dropped(self):
        srt = build_srt([(0.0, "  "), (1.0, "real")], 0.0, 5.0)
        assert srt.count("-->") == 1
        assert "real" in srt

    def test_cues_are_numbered_from_one_without_gaps(self):
        srt = build_srt([(0.0, "a"), (2.0, ""), (4.0, "c")], 0.0, 8.0)
        assert srt.startswith("1\n")
        assert "\n2\n" in srt
        assert "\n3\n" not in srt

    def test_no_cue_extends_past_the_video(self):
        srt = build_srt([(9.8, "tail")], 0.0, 10.0)
        assert "--> 00:00:10,000" in srt

    def test_empty_input_yields_empty_string(self):
        assert build_srt([], 0.0, 10.0) == ""

    def test_timecode_formats_hours_and_millis(self):
        srt = build_srt([(3661.5, "x")], 0.0, 3700.0)
        assert "01:01:01,500" in srt

    def test_cues_never_overlap(self):
        # The model emits fragments a few hundred ms apart. Padding each to a
        # readable length used to push its end past the next cue's start, which
        # players render stacked on top of each other.
        entries = [(i * 0.7, f"frag{i}") for i in range(12)]
        srt = build_srt(entries, 0.0, 30.0)
        spans = _parse_spans(srt)
        assert spans, "expected cues"
        for (_, end), (nxt_start, _) in zip(spans, spans[1:]):
            assert end <= nxt_start, f"cue ending {end} overlaps next at {nxt_start}"

    def test_rapid_fragments_merge_into_readable_cues(self):
        entries = [(0.0, "Entonces,"), (0.4, "obviamente"), (0.8, "habrá dos nombres.")]
        srt = build_srt(entries, 0.0, 10.0)
        assert srt.count("-->") == 1
        assert "Entonces, obviamente habrá dos nombres." in srt

    def test_merging_respects_the_character_cap(self):
        entries = [(i * 0.1, "x" * 40) for i in range(4)]
        srt = build_srt(entries, 0.0, 10.0)
        # 4x40 chars cannot collapse into one cue under an 84-char cap.
        assert srt.count("-->") > 1

    def test_last_cue_ends_at_the_video_duration(self):
        srt = build_srt([(0.0, "a"), (5.0, "b")], 0.0, 10.0)
        assert _parse_spans(srt)[-1][1] == pytest.approx(10.0)


class TestResolveVariantStatus:
    def test_all_completed(self):
        assert resolve_variant_status([{"status": "completed"}] * 3) == "completed"

    def test_all_failed(self):
        assert resolve_variant_status([{"status": "failed"}] * 3) == "failed"

    def test_mixed_is_partial(self):
        variants = [{"status": "completed"}, {"status": "failed"}]
        assert resolve_variant_status(variants) == "partial"

    def test_still_pending_is_partial_not_completed(self):
        variants = [{"status": "completed"}, {"status": "pending"}]
        assert resolve_variant_status(variants) == "partial"


class TestProgressMapping:
    """The record must actually move while a language streams.

    Concurrent languages all finished within a second of each other at the very
    end, so the record sat at 15% for the whole job and looked hung. Dubbing is
    now sequential and reports streaming position; these pin that mapping down.
    """

    def _processor(self, monkeypatch):
        import deps
        from unittest.mock import MagicMock

        import dubbing_processor

        writes = []
        fake = MagicMock()
        fake.update_dub_record = MagicMock(
            side_effect=lambda rid, updates: writes.append(updates)
        )
        monkeypatch.setattr(deps, "firestore_svc", fake)
        return dubbing_processor.DubbingProcessor(), writes

    def test_progress_spans_the_floor_to_ceiling_band(self, monkeypatch):
        from dubbing_processor import PROGRESS_CEILING, PROGRESS_FLOOR

        proc, writes = self._processor(monkeypatch)
        proc._write_progress("dub-x", [], 0, 0.0, 4)
        proc._write_progress("dub-x", [], 4, 0.0, 4)
        assert writes[0]["progress_pct"] == PROGRESS_FLOOR
        assert writes[-1]["progress_pct"] == PROGRESS_CEILING

    def test_progress_advances_within_a_single_language(self, monkeypatch):
        proc, writes = self._processor(monkeypatch)
        for fraction in (0.0, 0.25, 0.5, 0.75):
            proc._write_progress("dub-x", [], 0, fraction, 4)
        pcts = [w["progress_pct"] for w in writes]
        assert pcts == sorted(pcts) and len(set(pcts)) == 4, pcts

    def test_progress_is_monotonic_across_languages(self, monkeypatch):
        proc, writes = self._processor(monkeypatch)
        for step in range(4):
            for fraction in (0.0, 0.5):
                proc._write_progress("dub-x", [], step, fraction, 4)
        pcts = [w["progress_pct"] for w in writes]
        assert pcts == sorted(pcts)

    def test_progress_never_exceeds_the_ceiling(self, monkeypatch):
        from dubbing_processor import PROGRESS_CEILING

        proc, writes = self._processor(monkeypatch)
        # A language that overruns its share must not push past the band.
        proc._write_progress("dub-x", [], 4, 1.0, 4)
        assert writes[-1]["progress_pct"] == PROGRESS_CEILING

    def test_reporter_throttles_rapid_calls(self, monkeypatch):
        proc, writes = self._processor(monkeypatch)
        report = proc._progress_reporter("dub-x", [], 0, 4)
        for _ in range(50):
            report(0.5)
        # The sender fires this ~every 2.5s of audio; only the first should
        # reach Firestore inside one throttle window.
        assert len(writes) == 1


@pytest.fixture
def client(monkeypatch):
    """TestClient over the real app with Firestore mocked, authenticated as the
    master user so the write gate is not what is under test here."""
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    import deps
    from main import app

    monkeypatch.setenv("MASTER_INVITE_CODE", "test-master-code")
    monkeypatch.setattr(deps, "firestore_svc", MagicMock())
    return TestClient(app)


HEADERS = {"X-Invite-Code": "test-master-code"}


class TestCreateDubValidation:
    def test_valid_request_creates_one_variant_per_language(self, client):
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={"gcs_uri": "gs://b/uploads/a.mp4", "language_codes": ["es", "de"]},
        )
        assert res.status_code == 200
        import deps

        record = deps.firestore_svc.create_dub_record.call_args[0][0]
        assert [v.language_code for v in record.variants] == ["es", "de"]
        assert record.status == "pending"

    def test_unknown_language_is_rejected(self, client):
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={"gcs_uri": "gs://b/uploads/a.mp4", "language_codes": ["es", "xx"]},
        )
        assert res.status_code == 400
        assert "xx" in res.json()["detail"]

    def test_empty_language_list_is_rejected(self, client):
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={"gcs_uri": "gs://b/uploads/a.mp4", "language_codes": []},
        )
        assert res.status_code == 400

    def test_duplicate_codes_are_deduplicated(self, client):
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={
                "gcs_uri": "gs://b/uploads/a.mp4",
                "language_codes": ["es", "es", "es"],
            },
        )
        assert res.status_code == 200
        import deps

        record = deps.firestore_svc.create_dub_record.call_args[0][0]
        assert [v.language_code for v in record.variants] == ["es"]

    def test_too_many_languages_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("DUBBING_MAX_LANGUAGES", "2")
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={
                "gcs_uri": "gs://b/uploads/a.mp4",
                "language_codes": ["es", "de", "hi"],
            },
        )
        assert res.status_code == 400
        assert "At most 2" in res.json()["detail"]

    def test_oversized_source_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("DUBBING_MAX_SOURCE_MINUTES", "10")
        res = client.post(
            "/api/v1/dubbing",
            headers=HEADERS,
            json={
                "gcs_uri": "gs://b/uploads/a.mp4",
                "language_codes": ["es"],
                "duration_sec": 1200,
            },
        )
        assert res.status_code == 400
        assert "limit is 10 min" in res.json()["detail"]

    def test_languages_endpoint_reports_the_allowlist(self, client, monkeypatch):
        monkeypatch.setenv("DUBBING_LANGUAGES", "es,hi")
        res = client.get("/api/v1/dubbing/languages", headers=HEADERS)
        assert res.status_code == 200
        assert {lang["code"] for lang in res.json()["languages"]} == {"es", "hi"}


class TestDubRetryUpdates:
    def test_retry_resets_only_unfinished_variants(self):
        from models import DubRecord, DubVariant
        from routers.dubbing import _dub_retry_updates

        record = DubRecord(
            source_gcs_uri="gs://b/a.mp4",
            status="partial",
            variants=[
                DubVariant(
                    language_code="es",
                    status="completed",
                    output_gcs_uri="gs://b/dubs/x/es.mp4",
                ),
                DubVariant(language_code="de", status="failed", error_message="boom"),
            ],
        )
        updates = _dub_retry_updates(record)
        assert updates["status"] == "pending"
        done, retry = updates["variants"]
        # A completed language keeps its output instead of being re-dubbed.
        assert done["status"] == "completed"
        assert done["output_gcs_uri"] == "gs://b/dubs/x/es.mp4"
        assert retry["status"] == "pending"
        assert retry["error_message"] is None


class TestConfigGuards:
    def test_env_selects_a_subset_of_the_allowlist(self, monkeypatch):
        monkeypatch.setenv("DUBBING_LANGUAGES", "es,de")
        assert sorted(dubbing_config.supported_languages()) == ["de", "es"]

    def test_env_cannot_widen_the_allowlist(self, monkeypatch):
        # An unknown code in config must never become a valid target.
        monkeypatch.setenv("DUBBING_LANGUAGES", "es,klingon")
        assert sorted(dubbing_config.supported_languages()) == ["es"]

    def test_empty_env_falls_back_to_the_full_allowlist(self, monkeypatch):
        monkeypatch.setenv("DUBBING_LANGUAGES", "")
        assert sorted(dubbing_config.supported_languages()) == ["de", "es", "hi", "pt"]

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            dubbing_config.api_key()

    def test_blank_api_key_is_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            dubbing_config.api_key()
