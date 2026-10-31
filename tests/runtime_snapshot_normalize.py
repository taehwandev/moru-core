"""Normalize only declared volatile status fields; reject malformed evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

_HEX32 = frozenset("0123456789abcdef")
_PLACEHOLDER_SNAPSHOT_ID = "0" * 32
_PLACEHOLDER_CAPTURED_AT = "1970-01-01T00:00:00+00:00"


def _canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _validate_snapshot_id(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 32 or any(ch not in _HEX32 for ch in value):
        raise ValueError("Invalid snapshot_id: expected 32 lowercase hex characters")


def _validate_captured_at(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("Invalid captured_at: expected ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid captured_at: not a valid fromisoformat string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Invalid captured_at: timezone required with UTC offset zero")


def _normalize_snapshot_dict(target: dict[str, Any]) -> None:
    if "snapshot_id" not in target or "captured_at" not in target:
        raise ValueError("Missing required snapshot volatile fields")
    _validate_snapshot_id(target["snapshot_id"])
    _validate_captured_at(target["captured_at"])
    target["snapshot_id"] = _PLACEHOLDER_SNAPSHOT_ID
    target["captured_at"] = _PLACEHOLDER_CAPTURED_AT


def normalize_output(raw: bytes, kind: str) -> bytes:
    if not isinstance(raw, bytes):
        raise ValueError("raw must be bytes")
    if kind not in ("status", "validated_status", "trends"):
        raise ValueError(f"Unsupported kind: {kind!r}")
    try:
        decoded = raw.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Input is not valid UTF-8 JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Root JSON value must be an object")
    if raw != _canonical_bytes(parsed):
        raise ValueError("Input bytes are not in canonical JSON format")

    if kind == "status":
        _normalize_snapshot_dict(parsed)
    elif kind == "validated_status":
        if not isinstance(parsed.get("valid"), bool):
            raise ValueError("validated_status requires boolean 'valid'")
        failures = parsed.get("failures")
        if not isinstance(failures, list) or any(not isinstance(item, str) for item in failures):
            raise ValueError("validated_status requires list-of-string 'failures'")
        snapshot = parsed.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("validated_status requires dict 'snapshot'")
        _normalize_snapshot_dict(snapshot)
    elif kind == "trends":
        if "captured_at" not in parsed:
            raise ValueError("trends requires root 'captured_at'")
        _validate_captured_at(parsed["captured_at"])
        parsed["captured_at"] = _PLACEHOLDER_CAPTURED_AT

    return _canonical_bytes(parsed)
