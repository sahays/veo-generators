"""Pydantic <-> Firestore dict codec with document size guard."""

from __future__ import annotations

import json
from typing import TypeVar

from ..errors import DocTooLarge
from ..schema import ALL_NODE_TYPES, NodeBase

T = TypeVar("T", bound=NodeBase)


def check_doc_size(data: dict, max_bytes: int = 900_000) -> None:
    serialized = json.dumps(data, default=str).encode("utf-8")
    if len(serialized) > max_bytes:
        raise DocTooLarge(
            f"Document size {len(serialized)} bytes exceeds limit of {max_bytes} bytes"
        )


def encode(node: NodeBase, max_bytes: int = 900_000) -> dict:
    data = node.model_dump(mode="json")
    check_doc_size(data, max_bytes=max_bytes)
    return data


def decode(data: dict, cls: type[T] | None = None) -> T:
    if cls is None:
        node_type = data.get("node_type")
        if not node_type or node_type not in ALL_NODE_TYPES:
            raise ValueError(f"Unknown node_type: {node_type!r}")
        resolved_cls = ALL_NODE_TYPES[node_type]
        return resolved_cls.model_validate(data)  # type: ignore[return-value]
    return cls.model_validate(data)
