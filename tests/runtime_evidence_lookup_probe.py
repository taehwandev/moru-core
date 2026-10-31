"""Synthetic resolver fixtures and a fresh-process public-function probe."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

SESSION = {"runtime": "claude", "session_id": "synthetic-lookup"}
PROJECT = Path(__file__).resolve().parents[1]


def environment(base, source=PROJECT):
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("MORU_", "GIT_", "CODEX_", "CLAUDE_", "AGY_", "ANTIGRAVITY_", "SPILL_"))
        and k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONPYCACHEPREFIX")}
    env.update(HOME=str(base / "home"), MORU_STATE_HOME=str(base / "home/.moru"),
               MORU_HOME=str(source), PYTHONPATH=str(source / "scripts"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return env


def fixture(base, kind):
    from agent_run_registry import evidence_binding_key, register_run, registry_path

    project = base / kind
    project.mkdir()
    payload = json.dumps({"runtime_session": SESSION})

    def add(relative):
        path = project / ".moru" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        run = register_run(project, path, {"command": "task"}, {"request": "fixture"})
        path.write_text(payload)
        return path, run

    relative = "legacy/preflight.json" if kind == "custom" else "runs/" + "a" * 32 + "/preflight.json"
    active, run = add(relative)
    expected = str(active)
    if kind == "history_500":
        registry = registry_path(project)
        data = json.loads(registry.read_text())
        for i in range(500):
            history = active.parent.parent / f"{i:032x}" / active.name
            history.parent.mkdir()
            history.write_text(payload)
            data["runs"].append(dict(run, run_id=f"{i:032x}", state="completed",
                                      evidence_key=evidence_binding_key(project, history)))
        registry.write_text(json.dumps(data))
    elif kind == "cache_10000":
        for i in range(500):
            folder = project / ".moru/cache" / str(i)
            folder.mkdir(parents=True)
            for j in range(20):
                (folder / f"blob-{j}.json").write_text("{}")
    elif kind in ("ambiguous", "settled_tie"):
        second, _ = add("runs/" + "b" * 32 + "/preflight.json")
        expected = None if kind == "ambiguous" else str(active)
        registry = registry_path(project)
        data = json.loads(registry.read_text())
        data["runs"].reverse()
        for record in data["runs"]:
            record["owner"] = {}
            if kind == "settled_tie":
                record["state"] = "completed"
        registry.write_text(json.dumps(data))
        for path in (active, second):
            os.utime(path, (1700000000, 1700000000))
    elif kind.startswith("worker"):
        worker, _ = add("workers/0123456789abcdef/preflight.json")
        if kind == "worker_hint":
            expected = str(worker)
    elif kind == "nested_checkout":
        (active.parent / ".git").touch()
        expected = None
    elif kind == "file_symlink":
        target = active.with_name("other.json")
        active.rename(target)
        active.symlink_to(target)
        registry = registry_path(project)
        data = json.loads(registry.read_text())
        data["runs"][0]["evidence_key"] = evidence_binding_key(project, active)
        registry.write_text(json.dumps(data))
        expected = None
    elif kind == "moved_state":
        state = project / ".moru"
        target = project / "retained-state"
        state.rename(target)
        state.symlink_to(target, target_is_directory=True)
        # The binding key changes with the resolved path; retain its exact claim.
        registry = registry_path(project)
        data = json.loads(registry.read_text())
        data["runs"][0]["evidence_key"] = evidence_binding_key(project, active)
        registry.write_text(json.dumps(data))
        expected = str(active.resolve())
    return project, expected


def resolve(module, project, kind):
    options = {"states": frozenset({"completed"}), "latest_of_several": True} if kind == "settled_tie" else {}
    result = module.resolve_runtime_evidence(project, SESSION, **options)
    return str(result) if result is not None else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--kind", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source / "scripts"))
    if args.kind == "worker_hint":
        os.environ["MORU_WORKER_EVIDENCE"] = str(args.project / ".moru/workers/0123456789abcdef/preflight.json")
    import agent_runtime_session

    print(json.dumps({"resolved": resolve(agent_runtime_session, args.project, args.kind)}, sort_keys=True))


if __name__ == "__main__":
    main()
