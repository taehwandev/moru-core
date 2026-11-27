from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if Path(__file__).with_name("figma_summary_validate.py").is_file():
    from figma_summary_validate import _probe
else:
    _probe = None

__all__ = ["build_manifest"]


def build_manifest(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    receipt = _probe_manifest(summary, args, prepare=False)
    return receipt["manifest"] if receipt is not None else _build_manifest_reference(summary, args)


def _probe_manifest(summary, args, *, prepare):
    if _probe is None or type(summary) is not dict or (type(args) is not argparse.Namespace and type(args) is not SimpleNamespace):
        return None
    fields = vars(args)
    if (type(fields) is not dict or len(summary) > 32000 or len(fields) > 32000
            or any(type(key) is not str for key in summary) or any(type(key) is not str for key in fields)):
        return None
    schema = summary.get("schemaVersion", 3)
    if (type(schema) is not int or type(fields.get("format")) is not str
            or (type(fields.get("scale")) is not float and type(fields.get("scale")) is not int)
            or type(fields.get("max_flow_depth")) is not int or type(fields.get("no_images")) is not bool
            or type(fields.get("include_image_fills")) is not bool or type(fields.get("export_assets", False)) is not bool):
        return None
    arguments = _manifest_arguments(args)
    operation = "figma-bundle-prepare" if prepare else "figma-bundle-manifest"
    receipt = _probe(operation, {"summary": summary, "arguments": arguments}, __file__)
    if type(receipt) is not dict or set(receipt) != ({"manifest", "problems"} if prepare else {"manifest"}):
        return None
    if prepare and (type(receipt["problems"]) is not list or any(type(item) is not str for item in receipt["problems"])):
        return None
    manifest = receipt["manifest"]
    if (type(manifest) is not dict or list(manifest) != ["schemaVersion", "tool", "arguments", "summary"]
            or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != schema
            or manifest["tool"] != "figma-handoff.py" or type(manifest["arguments"]) is not dict
            or list(manifest["arguments"]) != list(arguments) or manifest["arguments"] != arguments
            or type(manifest["summary"]) is not dict or tuple(manifest["summary"]) != _COUNT_FIELDS
            or any(type(count) is not int or count < 0 for count in manifest["summary"].values())):
        return None
    return {**receipt, "manifest": {**manifest, "schemaVersion": schema, "arguments": arguments}}


_COUNT_FIELDS = (
    "screenCount", "flowEdgeCount", "flowInteractionCount", "namedColorStyleCount", "namedTextStyleCount",
    "namedEffectStyleCount", "variableCount", "referencedColorStyleCount", "referencedTextStyleCount",
    "referencedEffectStyleCount", "componentCount", "componentBlueprintCount", "colorCandidateCount",
    "gradientCandidateCount", "textStyleCandidateCount", "textRunCount", "effectCandidateCount",
    "layoutNodeCount", "renderedNodeCount", "excludedNodeCount", "assetCandidateCount", "assetInventoryCount",
)


def _manifest_arguments(args):
    return {
        "format": args.format,
        "scale": args.scale,
        "maxFlowDepth": args.max_flow_depth,
        "images": not args.no_images,
        "includeImageFills": args.include_image_fills,
        "exportAssets": getattr(args, "export_assets", False),
    }


def _build_manifest_reference(summary, args):
    return {
        "schemaVersion": summary.get("schemaVersion", 3),
        "tool": "figma-handoff.py",
        "arguments": _manifest_arguments(args),
        "summary": {
            "screenCount": len(summary["screens"]),
            "flowEdgeCount": len(summary["flowEdges"]),
            "flowInteractionCount": len(summary.get("flowInteractions", [])),
            "namedColorStyleCount": len(summary["designTokens"]["colorStyles"]),
            "namedTextStyleCount": len(summary["designTokens"]["textStyles"]),
            "namedEffectStyleCount": len(summary["designTokens"]["effectStyles"]),
            "variableCount": len(summary["designTokens"]["variables"].get("variables", [])),
            "referencedColorStyleCount": len(summary.get("referencedStyles", {}).get("colorStyles", [])),
            "referencedTextStyleCount": len(summary.get("referencedStyles", {}).get("textStyles", [])),
            "referencedEffectStyleCount": len(summary.get("referencedStyles", {}).get("effectStyles", [])),
            "componentCount": len(summary.get("components", [])),
            "componentBlueprintCount": len(summary.get("componentBlueprints", [])),
            "colorCandidateCount": len(summary["colors"]),
            "gradientCandidateCount": len(summary.get("gradients", [])),
            "textStyleCandidateCount": len(summary["textStyles"]),
            "textRunCount": len(summary.get("textRuns", [])),
            "effectCandidateCount": len(summary.get("effects", [])),
            "layoutNodeCount": len(summary.get("layoutNodes", [])),
            "renderedNodeCount": len(
                summary.get("implementationInventory", {}).get("renderedNodeIds", [])
            ),
            "excludedNodeCount": len(
                summary.get("implementationInventory", {}).get("excludedNodes", [])
            ),
            "assetCandidateCount": len(summary["assetCandidates"]),
            "assetInventoryCount": len(summary.get("assetInventory", [])),
        },
    }
