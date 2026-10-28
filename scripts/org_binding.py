"""Which organization guide a target project is bound to, and whether it is usable.

An organization guide is a private checkout shared by a company's or team's
repositories (`docs/org-guide-layer/prd.md`). Binding is decided only from
local evidence: the user's `~/.moru/orgs.json` map of Git remote patterns to
guide checkouts, and an optional tracked `.moru-org.json` pin in the project.
Nothing here reads guide content beyond its manifest; selection lives in
`org_layer.py`.

Every unusable state raises `OrgBindingError` rather than falling back: a
guessed organization, or a checkout other than the pinned one, would apply
rules the project did not ask for.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ORGS_FILE_ENV = "MORU_ORGS_FILE"
DEFAULT_ORGS_FILE = Path("~/.moru/orgs.json")
PROJECT_PIN_FILE = ".moru-org.json"
ORG_MANIFEST = "org.json"
ORG_ENTRY = "AGENTS.md"
ORG_SURFACES = "workflow-doc-surfaces.json"
SCHEMA_VERSION = 1
# The concerns on which a repository may not override its organization, and on
# which an organization may not override Moru without the run stopping.
PROTECTED_CONCERNS = ("security", "data", "deployment", "cost", "verification")
# The local Wikimap index written inside a guide checkout. It is excluded
# locally so indexing never makes the checkout look modified.
LOCAL_INDEX_DIR = ".wikimap"
ORG_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class OrgBindingError(ValueError):
    """A bound organization that cannot be used as declared."""


def orgs_file() -> Path:
    return Path(os.environ.get(ORGS_FILE_ENV) or DEFAULT_ORGS_FILE).expanduser()


def load_orgs() -> list[dict[str, Any]]:
    """The user's registered guides, or [] when none are registered."""

    path = orgs_file()
    if not path.is_file():
        return []
    payload = _read_json(path)
    orgs = payload.get("orgs") if isinstance(payload, dict) else None
    if not isinstance(orgs, list):
        raise OrgBindingError(f"{path}: expected an object with an `orgs` list")
    for org in orgs:
        if not isinstance(org, dict) or not ORG_ID.match(str(org.get("id", ""))):
            raise OrgBindingError(f"{path}: every org needs an id matching {ORG_ID.pattern}")
        if not isinstance(org.get("root"), str) or not isinstance(org.get("match", []), list):
            raise OrgBindingError(f"{path}: org {org['id']} needs a root path and a match list")
    return orgs


def normalize_remote(url: str) -> str:
    """`host/owner/repo` for an SSH or HTTPS Git remote, or "" for anything else."""

    match = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([^/:]+)[:/](.+)$", url.strip())
    if not match or "." not in match.group(1):
        return ""
    path = re.sub(r"^\d+/", "", match.group(2))
    path = re.sub(r"(\.git)?/*$", "", path)
    # Hosting services treat owner and repository names case-insensitively,
    # and patterns are lowered too, so compare the whole remote lowered.
    return f"{match.group(1)}/{path}".lower()


def project_remote(project: Path) -> str:
    completed = _git(project, "remote", "get-url", "origin")
    return normalize_remote(completed.stdout) if completed.returncode == 0 else ""


def read_pin(project: Path) -> dict[str, str] | None:
    path = project / PROJECT_PIN_FILE
    if not path.is_file():
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict) or not ORG_ID.match(str(payload.get("id", ""))):
        raise OrgBindingError(f"{PROJECT_PIN_FILE}: needs an org id matching {ORG_ID.pattern}")
    commit = payload.get("commit")
    if commit is not None and not (isinstance(commit, str) and _SHA.match(commit)):
        raise OrgBindingError(f"{PROJECT_PIN_FILE}: commit must be a full 40-character SHA")
    return {"id": payload["id"], **({"commit": commit} if commit else {})}


def resolve_binding(project: Path) -> dict[str, Any] | None:
    """The organization this project uses, or None when it uses none.

    A project pin names the organization outright; otherwise the origin remote
    must match exactly one registered pattern.
    """

    pin = read_pin(project)
    orgs = load_orgs()
    if pin:
        chosen = [org for org in orgs if org["id"] == pin["id"]]
        if not chosen:
            raise OrgBindingError(
                f"{PROJECT_PIN_FILE} pins org `{pin['id']}`, which is not registered in {orgs_file()}"
            )
        return _usable(chosen[0], "pin", pin.get("commit"))
    if not orgs:
        return None
    remote = project_remote(project)
    if not remote:
        return None
    matched = [
        org for org in orgs
        if any(fnmatch.fnmatchcase(remote, str(pattern).lower()) for pattern in org.get("match", []))
    ]
    if not matched:
        return None
    if len(matched) > 1:
        names = ", ".join(org["id"] for org in matched)
        raise OrgBindingError(f"remote {remote} matches several orgs ({names}); pin one in {PROJECT_PIN_FILE}")
    return _usable(matched[0], "pattern", None)


def _usable(org: dict[str, Any], binding: str, pinned: str | None) -> dict[str, Any]:
    root = Path(org["root"]).expanduser().resolve()
    if not (root / ORG_MANIFEST).is_file():
        raise OrgBindingError(f"org `{org['id']}`: no {ORG_MANIFEST} at {root}")
    commit = head_commit(root)
    if not commit:
        raise OrgBindingError(f"org `{org['id']}`: {root} is not a Git checkout with a commit")
    if pinned and pinned != commit:
        raise OrgBindingError(
            f"org `{org['id']}`: pinned commit {pinned} is not the checkout HEAD {commit}"
        )
    if not is_clean(root):
        raise OrgBindingError(
            f"org `{org['id']}`: {root} has uncommitted changes; guides are read only from a committed state"
        )
    manifest = validate_manifest(root, org["id"])
    return {
        "id": org["id"],
        "root": str(root),
        "commit": commit,
        "binding": binding,
        "enforce": manifest.get("enforce", []),
    }


def validate_manifest(root: Path, org_id: str) -> dict[str, Any]:
    payload = _read_json(root / ORG_MANIFEST)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise OrgBindingError(f"org `{org_id}`: {ORG_MANIFEST} needs schema_version {SCHEMA_VERSION}")
    if payload.get("id") != org_id:
        raise OrgBindingError(f"org `{org_id}`: {ORG_MANIFEST} declares id `{payload.get('id')}`")
    enforce = payload.get("enforce", [])
    if not isinstance(enforce, list):
        raise OrgBindingError(f"org `{org_id}`: {ORG_MANIFEST} enforce must be a list")
    for item in enforce:
        if (
            not isinstance(item, dict)
            or item.get("concern") not in PROTECTED_CONCERNS
            or not isinstance(item.get("doc"), str)
        ):
            raise OrgBindingError(
                f"org `{org_id}`: each enforce item needs a doc and a concern in {PROTECTED_CONCERNS}"
            )
    return payload


def head_commit(root: Path) -> str:
    completed = _git(root, "rev-parse", "HEAD")
    sha = completed.stdout.strip()
    return sha if completed.returncode == 0 and _SHA.match(sha) else ""


def is_clean(root: Path) -> bool:
    """No tracked or untracked change, apart from the local search index."""

    completed = _git(root, "status", "--porcelain", "--", ".", f":(exclude){LOCAL_INDEX_DIR}")
    return completed.returncode == 0 and not completed.stdout.strip()


def untracked_paths(root: Path, relatives: list[str]) -> list[str]:
    """Which of these paths HEAD does not track (ignored files look clean)."""

    completed = _git(root, "ls-files", "-z", "--", *relatives)
    tracked = set(completed.stdout.split("\0")) if completed.returncode == 0 else set()
    return [relative for relative in relatives if relative not in tracked]


def exclude_local_index(root: Path) -> None:
    """Keep the guide's local search index out of `git status` in that checkout."""

    completed = _git(root, "rev-parse", "--git-path", "info/exclude")
    if completed.returncode != 0:
        return
    exclude = Path(completed.stdout.strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    line = f"/{LOCAL_INDEX_DIR}/"
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if line not in existing.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n") + line + "\n",
                           encoding="utf-8")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args, 1, "", "")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrgBindingError(f"{path}: unreadable JSON ({error})") from error
