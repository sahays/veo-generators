"""Stem mixer gain math and routing (music ducks under dialogue only, never SFX)."""

from __future__ import annotations

import pytest
from storygraph.assembly.music import SceneSegment
from storygraph.assembly.music_ffmpeg import build_mix_filter
from storygraph.audio.stems.graph import StemLevels, compute_gains, stem_mix_graph
from storygraph.audio.stems.loudness import db_to_linear, loudness_gain_db
from storygraph.config import AssemblyCfg
from storygraph.schema import StemMix


def test_gain_math_targets_lufs_caps_boost_and_never_pumps_silence() -> None:
    assert loudness_gain_db(-20.0, -16.0, 18.0) == 4.0
    assert loudness_gain_db(-60.0, -24.0, 6.0) == 6.0  # quiet bed: boost capped
    assert loudness_gain_db(-8.0, -16.0, 6.0) == -8.0  # loud stem: attenuation uncapped
    assert loudness_gain_db(None, -16.0, 18.0, user_gain_db=-3.0) == -3.0
    assert loudness_gain_db(-75.0, -16.0, 18.0) == 0.0  # below gate = silent
    assert db_to_linear(-6.0) == pytest.approx(0.501, abs=1e-3)


def test_compute_gains_adds_user_trims_per_stem() -> None:
    mix = StemMix(dialogue_uri="d", sfx_uri="s", sfx_gain_db=-2.0, music_gain_db=1.5)
    gains = compute_gains(mix, StemLevels(dialogue=-22.0, sfx=-26.0, music=-30.0))
    assert (gains.dialogue_db, gains.sfx_db, gains.music_db) == (6.0, 0.0, 5.5)


def test_music_sidechain_is_keyed_on_dialogue_not_sfx() -> None:
    mix = StemMix(dialogue_uri="d", sfx_uri="s", duck_ratio=6.0)
    gains = compute_gains(mix, StemLevels(-16.0, -24.0, -26.0))
    graph = stem_mix_graph(mix, gains, has_music=True)
    assert "[1:a]" in graph.split("asplit=2[dia][key]")[0]  # key comes from dialogue
    assert "[mus][key]sidechaincompress" in graph and ":ratio=6.0" in graph
    assert "[dia][sfx][ducked]amix=inputs=3" in graph
    assert "[3:a]" not in stem_mix_graph(mix, gains, has_music=False)


def test_assembly_music_bed_uses_dialogue_key_input_when_given() -> None:
    segs = [SceneSegment("scn", 0.0, 8.0, b"m")]
    inputs, graph = build_mix_filter(segs, AssemblyCfg(), keyed=True)
    assert inputs == [0]
    assert "[2:a]" in graph and "[0:a]anull[dia]" in graph  # key = input after music
    assert "asplit" not in graph
    _, legacy = build_mix_filter(segs, AssemblyCfg())
    assert "[0:a]asplit=2[dia][key]" in legacy
