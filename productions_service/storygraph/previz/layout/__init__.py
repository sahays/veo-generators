"""Location layout: one VLM read of the scene plate -> deterministic, versioned 3D set."""

from .cache import (
    ScenePlate,
    input_colors,
    layout_for_location,
    layout_for_scene,
    location_request,
)
from .colors import dominant_color, entity_colors
from .estimate import (
    LayoutEstimator,
    LayoutObs,
    LayoutRequest,
    build_layout,
    source_hash,
)

__all__ = [
    "LayoutEstimator",
    "LayoutObs",
    "LayoutRequest",
    "ScenePlate",
    "build_layout",
    "dominant_color",
    "entity_colors",
    "input_colors",
    "layout_for_location",
    "layout_for_scene",
    "location_request",
    "source_hash",
]
