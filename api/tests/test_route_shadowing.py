"""Guards against literal routes being shadowed by `/{record_id}`.

FastAPI matches routes in registration order, so a literal single-segment path
(`/adapts/presets`, `/dubbing/languages`) registered *after* the
`GET /{record_id}` that `routers/_crud.register_crud_routes` adds is silently
unreachable: the id route matches first and the endpoint returns whatever
signing a bogus record produces.

This bit both the adapts presets endpoint (the UI rendered "no presets" for
months, because the frontend `.catch`es the call) and the dubbing languages
endpoint. The structural test below catches the whole class rather than the two
instances, so a new feature router cannot reintroduce it.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MASTER_INVITE_CODE", "test-master-code")

from main import app  # noqa: E402

_PARAM = re.compile(r"^\{[^}]+\}$")


def _api_routes():
    return [r for r in app.routes if getattr(r, "methods", None) and hasattr(r, "path")]


def test_no_literal_route_is_shadowed_by_a_path_param_route():
    """For every (prefix, method, depth), a literal segment must be registered
    before the `{param}` route that would otherwise capture it."""
    # registration index -> keeps the ordering FastAPI actually resolves with
    param_first: dict[tuple, int] = {}
    shadowed = []

    for index, route in enumerate(_api_routes()):
        segments = [s for s in route.path.split("/") if s]
        if not segments:
            continue
        prefix, last = "/".join(segments[:-1]), segments[-1]
        for method in route.methods:
            key = (prefix, method, len(segments))
            if _PARAM.match(last):
                param_first.setdefault(key, index)
            elif key in param_first and index > param_first[key]:
                shadowed.append(f"{method} {route.path}")

    assert not shadowed, (
        "these literal routes are registered after a sibling /{param} route "
        f"and are unreachable: {sorted(set(shadowed))}"
    )


def test_known_previously_shadowed_endpoints_resolve():
    """Direct regression cover for the two endpoints that were actually broken."""
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    import deps

    deps.firestore_svc = MagicMock()
    client = TestClient(app)
    headers = {"X-Invite-Code": os.environ["MASTER_INVITE_CODE"]}

    presets = client.get("/api/v1/adapts/presets", headers=headers).json()
    assert "ott" in presets["presets"]

    languages = client.get("/api/v1/dubbing/languages", headers=headers).json()
    assert {lang["code"] for lang in languages["languages"]}
