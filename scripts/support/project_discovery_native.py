"""Optional one-process native discovery; existing Python policy owns fallback.

Owner: discovery result adapter. Allowed: stdlib and project result types (lazy).
Forbidden: traversal/selection policy, caches, installs, state writes or effects.
Callers/tests: agent_project_discovery; test_native_project_discovery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def native_discovery(request, cwd, *, search_roots, registry_snapshot, max_depth,
                     include_default_search_roots):
    if (os.environ.get("MORU_LAUNCHER_BACKEND") == "python"
            or os.environ.get("MORU_DISCOVERY_NATIVE_DECLINED") == "1"):
        return None
    if registry_snapshot.get("workspace_groups"):
        return None
    entry = Path.home() / ".moru/bin/moru-hook"
    binary = entry.with_name("moru-hook-native")
    if not binary.is_file():
        return None
    args = [str(binary), str(entry), "project-discover", "--native-probe",
            "--registry-stdin", "--request", request, "--cwd", str(cwd),
            "--max-depth", str(max_depth), "--format", "json"]
    for root in search_roots:
        args += ["--search-root", str(root)]
    if include_default_search_roots:
        args += ["--include-default-search-roots"]
    try:
        done = subprocess.run(args, input=json.dumps(registry_snapshot).encode(),
                              env={**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])},
                              capture_output=True, timeout=10)
        if done.returncode not in (0, 2, 3) or done.stderr:
            return None
        value = json.loads(done.stdout)
        if (set(value) != {"status", "candidates", "selected_project"}
                or {"selected": 0, "ambiguous": 2, "not_found": 3}.get(value["status"]) != done.returncode):
            return None
        from agent_project_types import DiscoveryResult, ProjectCandidate
        def candidate(raw):
            return ProjectCandidate(path=Path(raw["path"]), confidence=raw["confidence"],
                reasons=raw["reasons"], instruction_files=raw["instruction_files"],
                markers=raw["markers"], sources=raw["sources"], aliases=raw["aliases"])
        return DiscoveryResult(status=value["status"],
            candidates=[candidate(raw) for raw in value["candidates"]],
            selected=candidate(value["selected_project"]) if value["selected_project"] else None)
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return None
