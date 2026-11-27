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
    if _probe is not None and type(summary) is dict and (type(args) is argparse.Namespace or type(args) is SimpleNamespace):
        fields = vars(args)
        schema = summary.get("schemaVersion", 3)
        if (type(schema) is int and type(fields.get("format")) is str
                and (type(fields.get("scale")) is float or type(fields.get("scale")) is int)
                and type(fields.get("max_flow_depth")) is int and type(fields.get("no_images")) is bool
                and type(fields.get("include_image_fills")) is bool and type(fields.get("export_assets", False)) is bool):
            arguments = _manifest_arguments(args)
            receipt = _probe("figma-bundle-manifest", {"summary": summary, "arguments": arguments}, __file__)
            if type(receipt) is dict and set(receipt) == {"manifest"}:
                manifest = receipt["manifest"]
                if (type(manifest) is dict and list(manifest) == ["schemaVersion", "tool", "arguments", "summary"]
                        and type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == schema
                        and manifest["tool"] == "figma-handoff.py" and type(manifest["arguments"]) is dict
                        and list(manifest["arguments"]) == list(arguments) and manifest["arguments"] == arguments
                        and type(manifest["summary"]) is dict and tuple(manifest["summary"]) == _COUNT_FIELDS
                        and all(type(count) is int and count >= 0 for count in manifest["summary"].values())):
                    return {**manifest, "schemaVersion": schema, "arguments": arguments}
    return _build_manifest_reference(summary, args)


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
