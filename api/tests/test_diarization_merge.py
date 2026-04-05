"""Unit tests for Chirp diarization chunk merging — offset and continuity."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from diarization_service import _merge_chunk_results, _merge_adjacent_segments


class TestMergeChunkResults:
    """Verify time offsets are applied and cross-boundary merging works."""

    def test_single_chunk_no_offset(self):
        results = [
            {
                "speaker_segments": [
                    {
                        "speaker_id": "Speaker 1",
                        "start_sec": 0.0,
                        "end_sec": 10.0,
                        "confidence": 0.9,
                    },
                ],
                "transcript": "hello",
            }
        ]
        merged = _merge_chunk_results(results, [0.0], "[test]")
        assert len(merged["speaker_segments"]) == 1
        assert merged["speaker_segments"][0]["start_sec"] == 0.0
        assert merged["speaker_segments"][0]["end_sec"] == 10.0

    def test_two_chunks_offsets_applied(self):
        """Chunk 2 segments should be offset by 1200s."""
        results = [
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 0.0, "end_sec": 600.0},
                    {"speaker_id": "Speaker 2", "start_sec": 600.0, "end_sec": 1200.0},
                ],
                "transcript": "chunk one",
            },
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 0.0, "end_sec": 100.0},
                ],
                "transcript": "chunk two",
            },
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0], "[test]")
        segs = merged["speaker_segments"]
        # Last segment should be offset: 0+1200=1200, 100+1200=1300
        last = segs[-1]
        assert last["start_sec"] == 1200.0
        assert last["end_sec"] == 1300.0

    def test_cross_boundary_same_speaker_not_merged(self):
        """Same speaker name across chunks gets prefixed — NOT merged."""
        results = [
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 500.0, "end_sec": 1200.0},
                ],
                "transcript": "one",
            },
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 0.0, "end_sec": 300.0},
                ],
                "transcript": "two",
            },
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0], "[test]")
        segs = merged["speaker_segments"]
        # Chunk-prefixed: "C1 Speaker 1" != "C2 Speaker 1" — kept separate
        assert len(segs) == 2
        assert segs[0]["speaker_id"] == "C1 Speaker 1"
        assert segs[1]["speaker_id"] == "C2 Speaker 1"

    def test_cross_boundary_different_speakers_not_merged(self):
        results = [
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 900.0, "end_sec": 1200.0},
                ],
                "transcript": "one",
            },
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 2", "start_sec": 0.0, "end_sec": 300.0},
                ],
                "transcript": "two",
            },
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0], "[test]")
        segs = merged["speaker_segments"]
        assert len(segs) == 2

    def test_three_chunks_prefixed(self):
        results = [
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 0.0, "end_sec": 1200.0},
                ],
                "transcript": "a",
            },
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 2", "start_sec": 0.0, "end_sec": 1200.0},
                ],
                "transcript": "b",
            },
            {
                "speaker_segments": [
                    {"speaker_id": "Speaker 1", "start_sec": 0.0, "end_sec": 500.0},
                ],
                "transcript": "c",
            },
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0, 2400.0], "[test]")
        segs = merged["speaker_segments"]
        assert segs[0]["speaker_id"] == "C1 Speaker 1"
        assert segs[1]["speaker_id"] == "C2 Speaker 2"
        assert segs[2]["speaker_id"] == "C3 Speaker 1"
        assert segs[2]["start_sec"] == 2400.0
        assert segs[2]["end_sec"] == 2900.0

    def test_transcripts_concatenated(self):
        results = [
            {"speaker_segments": [], "transcript": "hello"},
            {"speaker_segments": [], "transcript": "world"},
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0], "[test]")
        assert merged["transcript"] == "hello world"

    def test_empty_chunks(self):
        results = [
            {"speaker_segments": [], "transcript": ""},
            {"speaker_segments": [], "transcript": ""},
        ]
        merged = _merge_chunk_results(results, [0.0, 1200.0], "[test]")
        assert merged["speaker_segments"] == []
        assert merged["transcript"] == ""


class TestMergeAdjacentSegments:
    def test_same_speaker_merged(self):
        segs = [
            {"speaker_id": "A", "start_sec": 0, "end_sec": 5},
            {"speaker_id": "A", "start_sec": 5, "end_sec": 10},
        ]
        result = _merge_adjacent_segments(segs)
        assert len(result) == 1
        assert result[0]["end_sec"] == 10

    def test_different_speakers_not_merged(self):
        segs = [
            {"speaker_id": "A", "start_sec": 0, "end_sec": 5},
            {"speaker_id": "B", "start_sec": 5, "end_sec": 10},
        ]
        result = _merge_adjacent_segments(segs)
        assert len(result) == 2

    def test_alternating_speakers(self):
        segs = [
            {"speaker_id": "A", "start_sec": 0, "end_sec": 3},
            {"speaker_id": "B", "start_sec": 3, "end_sec": 6},
            {"speaker_id": "A", "start_sec": 6, "end_sec": 9},
        ]
        result = _merge_adjacent_segments(segs)
        assert len(result) == 3

    def test_empty(self):
        assert _merge_adjacent_segments([]) == []
