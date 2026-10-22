"""Pipeline stage identifiers and ordering for the StoryGraph controller."""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    S0_INGEST = "S0_INGEST"
    S1_EXTRACT = "S1_EXTRACT"
    S2_SCREENPLAY = "S2_SCREENPLAY"
    S3_DESIGN = "S3_DESIGN"
    S4_SHOTS = "S4_SHOTS"
    S5_MUSIC = "S5_MUSIC"
    S6_VALIDATE = "S6_VALIDATE"
    S7_COMPILE = "S7_COMPILE"
    S8_KEYFRAMES = "S8_KEYFRAMES"
    S8_RENDER = "S8_RENDER"
    S9_QA = "S9_QA"
    S10_ASSEMBLE = "S10_ASSEMBLE"


STAGE_ORDER: list[Stage] = list(Stage)

AUTHORING_STAGES: frozenset[Stage] = frozenset(
    {
        Stage.S0_INGEST,
        Stage.S1_EXTRACT,
        Stage.S2_SCREENPLAY,
        Stage.S3_DESIGN,
        Stage.S4_SHOTS,
        Stage.S5_MUSIC,
    }
)
