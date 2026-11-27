from __future__ import annotations

import hashlib
import json
from typing import Any

from figma_native_probe import request as _probe
from figma_util import normalize_node_id

__all__ = ["AssetAnalysis"]

_SIGNATURE_FIELDS = (
    "type", "name", "size", "absoluteBoundingBox", "fills", "strokes",
    "strokeWeight", "strokeAlign", "individualStrokeWeights", "cornerRadius",
    "rectangleCornerRadii", "effects", "opacity", "blendMode", "fillGeometry", "strokeGeometry",
)


def _native_assets(operation: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    receipt = _probe(operation, rows, __file__)
    if type(receipt) is not dict or set(receipt) != {"assets_json"} or type(receipt["assets_json"]) is not str:
        return None
    try:
        assets = json.loads(receipt["assets_json"])
    except (ValueError, RecursionError):
        return None
    if type(assets) is list and all(type(row) is dict for row in assets):
        return assets
    return None


def _asset_dedup_key(node: dict[str, Any], image_refs: list[str]) -> str:
    if image_refs:
        return "img:" + ",".join(sorted(image_refs))
    signature = {field: node[field] for field in _SIGNATURE_FIELDS if field in node}
    digest = hashlib.sha1(json.dumps(signature, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return "vec:" + digest


_GENERIC_NAME_PREFIXES = (
    "vector", "rectangle", "group", "union", "ellipse", "subtract", "frame",
    "mask", "shape", "path", "intersect", "exclude", "line",
)


def _is_generic_name(name: Any) -> bool:
    text = str(name or "").strip().lower()
    return not text or any(text.startswith(prefix) for prefix in _GENERIC_NAME_PREFIXES)


def _pick_representative_name(names: list[str], nearest_names: list[str]) -> str:
    for name in names:
        if not _is_generic_name(name):
            return name
    if nearest_names:
        return nearest_names[0]
    return names[0] if names else ""


def _build_asset_inventory(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if type(candidates) is list and candidates and len(candidates) <= 32000:
        assets = _native_assets("figma-asset-inventory", candidates)
        if assets is not None:
            return assets
    return _build_asset_inventory_reference(candidates)


def _build_asset_inventory_reference(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for candidate in candidates:
        key = candidate.get("dedupKey") or candidate.get("id") or ""
        group = groups.get(key)
        if group is None:
            group = {
                "type": candidate.get("type", ""),
                "nodeIds": [],
                "names": [],
                "imageRefs": candidate.get("imageRefs") or [],
                "nearestNames": [],
            }
            groups[key] = group
            order.append(key)
        if candidate.get("id"):
            group["nodeIds"].append(candidate["id"])
        if candidate.get("name"):
            group["names"].append(str(candidate["name"]))
        nearest = candidate.get("nearestComponentName")
        if nearest:
            group["nearestNames"].append(str(nearest))

    inventory: list[dict[str, Any]] = []
    for key in order:
        group = groups[key]
        entry: dict[str, Any] = {
            "dedupKey": key,
            "name": _pick_representative_name(group["names"], group["nearestNames"]),
            "type": group["type"],
            "usageCount": len(group["nodeIds"]),
            "nodeIds": group["nodeIds"],
            "nameUnclear": all(_is_generic_name(name) for name in group["names"]) if group["names"] else True,
        }
        if group["imageRefs"]:
            entry["imageRefs"] = group["imageRefs"]
        if group["nearestNames"]:
            entry["nearestComponentName"] = group["nearestNames"][0]
        inventory.append(entry)
    inventory.sort(key=lambda entry: (-entry["usageCount"], entry["dedupKey"]))
    return inventory


def _summarize_asset_candidates(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if type(nodes) is list and nodes and len(nodes) <= 32000 and all(type(node) is dict for node in nodes):
        fields = ("id", "exportSettings", *_SIGNATURE_FIELDS)
        projected = [{key: node[key] for key in fields if key in node} for node in nodes]
        assets = _native_assets("figma-asset-candidates", projected)
        if assets is not None:
            return assets
    return _summarize_asset_candidates_reference(nodes)


def _summarize_asset_candidates_reference(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        export_settings = node.get("exportSettings") or []
        image_refs: list[str] = []
        for field in ("fills", "strokes"):
            for paint in node.get(field, []) or []:
                if isinstance(paint, dict) and paint.get("type") == "IMAGE" and paint.get("imageRef"):
                    image_refs.append(str(paint["imageRef"]))
        if export_settings or image_refs or node.get("type") in {"VECTOR", "BOOLEAN_OPERATION"}:
            candidates.append(
                {
                    "id": normalize_node_id(str(node.get("id", ""))),
                    "name": node.get("name", ""),
                    "type": node.get("type", ""),
                    "exportSettings": export_settings,
                    "imageRefs": image_refs,
                    "dedupKey": _asset_dedup_key(node, image_refs),
                }
            )
    return candidates


class AssetAnalysis:
    """Asset candidate and deduplicated inventory analysis family."""

    build_asset_inventory = staticmethod(_build_asset_inventory)
    summarize_asset_candidates = staticmethod(_summarize_asset_candidates)
