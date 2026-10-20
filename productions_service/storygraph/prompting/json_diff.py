"""Canonical spec hashing + JSON diff producing typed `PatchOp`s (parent -> child).

Hashing canonicalises key order and whitespace so a human re-submitting the same spec
with different formatting dedupes onto the existing `PromptVersion`.
Diff is a single recursive walk: O(size of both documents).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..schema import PatchOp

JsonValue = Any  # parsed JSON (dict | list | str | int | float | bool | None)


def canonical_json(spec_json: str) -> str:
    """Return the key-sorted, whitespace-free form of a JSON document."""
    return json.dumps(json.loads(spec_json), sort_keys=True, separators=(",", ":"))


def spec_hash(spec_json: str) -> str:
    """SHA-256 of the canonical JSON form (formatting-insensitive identity)."""
    return hashlib.sha256(canonical_json(spec_json).encode("utf-8")).hexdigest()


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _diff_dict(
    old: dict[str, JsonValue], new: dict[str, JsonValue], path: str
) -> list[PatchOp]:
    ops: list[PatchOp] = []
    for key in old.keys() - new.keys():
        ops.append(PatchOp(op="remove", path=f"{path}/{_escape(key)}"))
    for key, value in new.items():
        child = f"{path}/{_escape(key)}"
        if key not in old:
            ops.append(PatchOp(op="add", path=child, value=value))
        else:
            ops.extend(_diff(old[key], value, child))
    return ops


def _diff_list(old: list[JsonValue], new: list[JsonValue], path: str) -> list[PatchOp]:
    if len(old) != len(
        new
    ):  # reorder/insert: whole-list replace keeps patches readable
        return [PatchOp(op="replace", path=path or "/", value=new)]
    ops: list[PatchOp] = []
    for i, (a, b) in enumerate(zip(old, new, strict=True)):
        ops.extend(_diff(a, b, f"{path}/{i}"))
    return ops


def _diff(old: JsonValue, new: JsonValue, path: str) -> list[PatchOp]:
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_dict(old, new, path)
    if isinstance(old, list) and isinstance(new, list):
        return _diff_list(old, new, path)
    if old == new and type(old) is type(new):
        return []
    return [PatchOp(op="replace", path=path or "/", value=new)]


def diff_specs(parent_json: str, child_json: str) -> list[PatchOp]:
    """Patch ops turning `parent_json` into `child_json` (sorted keys for determinism)."""
    ops = _diff(json.loads(parent_json), json.loads(child_json), "")
    return sorted(ops, key=lambda op: op.path)
