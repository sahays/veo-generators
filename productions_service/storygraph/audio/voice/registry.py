"""Voice registry: one fixed TTS voice per speaking character, chosen once and reused forever.

Selection is deterministic: archetype -> candidate pool rotated by sha256(entity id), skipping
voices already held by other cast members (cast processed in id order). Existing voices
(auto or human-edited) are never reassigned; `set_voice` is the explicit edit path.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable

from ...repo import Repo
from ...schema import Entity, EntityType
from ...schemas.voice import VoiceArchetype, VoiceProfile
from .archetype import classify_archetype
from .catalog import ARCHETYPE_STYLE, ARCHETYPE_VOICES, candidates
from .logs import log_ctx

logger = logging.getLogger(__name__)
DEFAULT_TTS_MODEL = "gemini-2.5-flash-tts"
KNOWN_VOICES: frozenset[str] = frozenset(
    v for pool in ARCHETYPE_VOICES.values() for v in pool
)


def pick_voice_name(entity_id: str, archetype: VoiceArchetype, taken: set[str]) -> str:
    """Deterministic pool rotation by entity-id hash; first voice not taken by the cast."""
    pool = candidates(archetype)
    start = int(hashlib.sha256(entity_id.encode()).hexdigest(), 16) % len(pool)
    rotated = pool[start:] + pool[:start]
    return next((v for v in rotated if v not in taken), rotated[0])


def make_profile(
    entity_id: str, archetype: VoiceArchetype, taken: set[str], model: str
) -> VoiceProfile:
    return VoiceProfile(
        model=model,
        voice_name=pick_voice_name(entity_id, archetype, taken),
        archetype=archetype,
        style_prompt=ARCHETYPE_STYLE[archetype],
    )


def assign_cast_voices(
    speakers: Iterable[Entity], cast: list[Entity], source: str, model: str
) -> dict[str, VoiceProfile]:
    """Pure: keep existing voices, assign new ones in id order avoiding cast collisions."""
    names = {
        e.id: [e.canonical_name, *e.aliases]
        for e in cast
        if e.entity_type == EntityType.CHARACTER
    }
    out = {e.id: e.voice for e in cast if e.voice is not None}
    taken = {v.voice_name for v in out.values()}
    for ent in sorted(speakers, key=lambda e: e.id):
        if ent.id in out:
            continue
        others = [n for eid, ns in names.items() if eid != ent.id for n in ns]
        prof = make_profile(
            ent.id, classify_archetype(ent, source, others), taken, model
        )
        out[ent.id] = prof
        taken.add(prof.voice_name)
    return out


def ensure_cast_voices(
    repo: Repo, speaker_ids: Iterable[str], model: str = DEFAULT_TTS_MODEL
) -> dict[str, VoiceProfile]:
    """Load-or-assign voices for `speaker_ids`, persisting newly chosen ones on the Entity."""
    cast = repo.list_entities()
    wanted = set(speaker_ids)
    speakers = [e for e in cast if e.id in wanted]
    voices = assign_cast_voices(speakers, cast, repo.get_source_text(), model)
    for ent in speakers:
        if ent.voice is None:
            repo.put_entity(ent.model_copy(update={"voice": voices[ent.id]}))
            logger.info(
                "Fixed TTS voice assigned",
                extra=log_ctx(
                    "audio.voice.registry",
                    "voice_assigned",
                    "speaking character had no fixed voice",
                    "archetype + sha256(entity_id) pool rotation",
                    entity_id=ent.id,
                    voice_name=voices[ent.id].voice_name,
                    archetype=voices[ent.id].archetype,
                ),
            )
    return {k: v for k, v in voices.items() if k in wanted}


def set_voice(
    repo: Repo, entity_id: str, voice_name: str, style_prompt: str | None = None
) -> Entity:
    """Human edit of a character's fixed voice (validated against the prebuilt catalog)."""
    ent = repo.get_entity(entity_id)
    if ent is None:
        raise ValueError(f"Entity {entity_id} not found")
    if voice_name not in KNOWN_VOICES:
        raise ValueError(f"Unknown Gemini TTS voice '{voice_name}'")
    base = ent.voice or VoiceProfile(voice_name=voice_name)
    update: dict[str, object] = {"voice_name": voice_name, "selected_by": "human"}
    if style_prompt is not None:
        update["style_prompt"] = style_prompt
    saved = repo.put_entity(
        ent.model_copy(update={"voice": base.model_copy(update=update)})
    )
    logger.info(
        "Fixed TTS voice edited",
        extra=log_ctx(
            "audio.voice.registry",
            "voice_edited",
            "human override",
            "set_voice",
            entity_id=entity_id,
            voice_name=voice_name,
        ),
    )
    return saved
