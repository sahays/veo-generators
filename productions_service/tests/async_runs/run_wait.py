"""Shared helpers for async-run tests: create a production and wait for its run to settle."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient


def create_production(client: TestClient, auto_approve: bool = True) -> str:
    payload = {
        "name": "Monsoon Protocol",
        "type": "movie",
        "base_concept": "Detective Arjun meets Dr. Meera at a rain-lit cafe with a brass compass.",
        "video_length": "16",
        "orientation": "16:9",
        "language": "en-IN",
        "auto_approve_gates": auto_approve,
    }
    res = client.post("/api/v1/productions", json=payload)
    assert res.status_code == 200
    return str(res.json()["id"])


def status(client: TestClient, pid: str) -> dict[str, Any]:
    res = client.get(f"/api/v1/productions/{pid}/status")
    assert res.status_code == 200
    return dict(res.json())


def wait_until_idle(
    client: TestClient, pid: str, timeout_s: float = 60.0
) -> dict[str, Any]:
    """Poll the status endpoint until no run is live; returns the final status."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        st = status(client, pid)
        if st["active_run"] is None:
            return st
        time.sleep(0.02)
    raise AssertionError(f"run of {pid} still live after {timeout_s}s")
