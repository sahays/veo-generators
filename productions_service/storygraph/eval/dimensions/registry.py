"""Ordered registry of every eval dimension (declaration order = report order)."""

from __future__ import annotations

from .action import ActionAdherence
from .audio import AudioDimension
from .base import Dimension
from .camera import CameraAdherence
from .character import CharacterConsistency
from .objects import ObjectPermanence
from .physics import PhysicalPlausibility
from .scene import SceneConsistency
from .script import ScriptAdherence
from .spatial import SpatialConsistency
from .style import StyleConsistency
from .temporal import TemporalConsistency


def all_dimensions() -> list[Dimension]:
    """Fresh instances of every dimension (stateless; safe to share)."""
    return [
        CharacterConsistency(),
        TemporalConsistency(),
        SpatialConsistency(),
        SceneConsistency(),
        ObjectPermanence(),
        PhysicalPlausibility(),
        ActionAdherence(),
        CameraAdherence(),
        StyleConsistency(),
        AudioDimension(),
        ScriptAdherence(),
    ]
