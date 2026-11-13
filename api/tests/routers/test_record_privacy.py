"""Record responses must never carry the creator's invite code.

An invite code is the app's credential. Feature records store the code of
whoever created them as provenance; a read-only guest who lists or opens a
record must not be able to read a power or master code out of the response.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("MASTER_INVITE_CODE", "test-master-code")

GUEST = {"X-Invite-Code": "privacy-guest-code"}
SECRET = "creator-power-code-0xC0FFEE"
VIDEO = "gs://test-bucket/uploads/film.mp4"


def _key_moments() -> Any:
    from models import KeyMomentsRecord

    return KeyMomentsRecord(id="rec-1", video_gcs_uri=VIDEO, invite_code=SECRET)


def _thumbnail() -> Any:
    from models import ThumbnailRecord

    return ThumbnailRecord(id="rec-1", video_gcs_uri=VIDEO, invite_code=SECRET)


def _reframe() -> Any:
    from models import ReframeRecord

    return ReframeRecord(id="rec-1", source_gcs_uri=VIDEO, invite_code=SECRET)


def _promo() -> Any:
    from models import PromoRecord

    return PromoRecord(id="rec-1", source_gcs_uri=VIDEO, invite_code=SECRET)


def _adapt() -> Any:
    from models import AdaptRecord

    return AdaptRecord(id="rec-1", source_gcs_uri=VIDEO, invite_code=SECRET)


def _dub() -> Any:
    from models import DubRecord

    return DubRecord(id="rec-1", source_gcs_uri=VIDEO, invite_code=SECRET)


def _production() -> Any:
    from models import Project

    return Project(id="rec-1", name="Ad", base_concept="A tea ad", invite_code=SECRET)


# (URL prefix, FirestoreService list method, get method, record factory)
FEATURES: list[tuple[str, str, str, Callable[[], Any]]] = [
    (
        "key-moments",
        "get_key_moments_analyses",
        "get_key_moments_analysis",
        _key_moments,
    ),
    ("thumbnails", "get_thumbnail_records", "get_thumbnail_record", _thumbnail),
    ("reframe", "get_reframe_records", "get_reframe_record", _reframe),
    ("promo", "get_promo_records", "get_promo_record", _promo),
    ("adapts", "get_adapt_records", "get_adapt_record", _adapt),
    ("dubbing", "get_dub_records", "get_dub_record", _dub),
    ("productions", "get_productions", "get_production", _production),
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """TestClient over the real app as a read-only guest, services mocked."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models_infra import InviteCode

    guest = InviteCode(
        id="inv-guest",
        code=GUEST["X-Invite-Code"],
        label="guest",
        is_active=True,
        daily_credits=1000,
        expires_at=None,
        createdAt=datetime.now(timezone.utc),
    )
    firestore, storage = MagicMock(), MagicMock()
    firestore.get_invite_code_by_value.side_effect = {guest.code: guest}.get
    storage.resolve_cached_url.side_effect = lambda uri, cache: ("signed", False)
    storage.get_signed_url.side_effect = lambda uri: "signed"
    storage.recover_gcs_uri.return_value = None
    monkeypatch.setattr(deps, "firestore_svc", firestore)
    monkeypatch.setattr(deps, "storage_svc", storage)
    return TestClient(app)


@pytest.mark.parametrize("prefix, lister, getter, factory", FEATURES)
def test_guest_reading_a_record_never_sees_the_creators_invite_code(
    client: Any, prefix: str, lister: str, getter: str, factory: Callable[[], Any]
) -> None:
    import deps

    record = factory()
    getattr(deps.firestore_svc, lister).return_value = [record]
    getattr(deps.firestore_svc, getter).return_value = record
    listed = client.get(f"/api/v1/{prefix}", headers=GUEST)
    one = client.get(f"/api/v1/{prefix}/rec-1", headers=GUEST)
    assert (listed.status_code, one.status_code) == (200, 200)
    assert [item["id"] for item in listed.json()] == ["rec-1"]
    assert one.json()["id"] == "rec-1"
    assert "invite_code" not in one.json()
    assert SECRET not in listed.text and SECRET not in one.text


@pytest.mark.parametrize("with_storage", [True, False])
def test_signing_helpers_drop_the_invite_code_with_and_without_storage(
    monkeypatch: pytest.MonkeyPatch, with_storage: bool
) -> None:
    import deps
    from url_signing import sign_production_urls, sign_record_urls

    storage = MagicMock()
    storage.resolve_cached_url.side_effect = lambda uri, cache: ("signed", False)
    storage.recover_gcs_uri.return_value = None
    monkeypatch.setattr(deps, "storage_svc", storage if with_storage else None)
    monkeypatch.setattr(deps, "firestore_svc", MagicMock())
    reframe = sign_record_urls(
        _reframe(), {"source_gcs_uri": "source_signed_url"}, lambda cache: None
    )
    production = sign_production_urls(_production())
    assert "invite_code" not in reframe and "invite_code" not in production
    assert reframe["source_gcs_uri"] == VIDEO and production["name"] == "Ad"
    assert ("source_signed_url" in reframe) is with_storage


def test_the_default_crud_serialiser_drops_the_invite_code() -> None:
    from url_signing import public_record_dict

    record = _key_moments()
    data = public_record_dict(record)
    assert "invite_code" not in data and data["video_gcs_uri"] == VIDEO
    assert record.invite_code == SECRET, "the stored record keeps its provenance"
