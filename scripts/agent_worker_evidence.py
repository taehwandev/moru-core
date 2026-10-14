"""Opaque reservation markers for isolated worker evidence directories."""

from __future__ import annotations

import hmac
import os
import uuid
from pathlib import Path

from agent_gate_evidence import gate_evidence_path_for_preflight
from support.global_state import project_state_dir_target


MORU_RESERVATION_FILENAME = ".moru-reservation"


def _reservation_paths(worker_dir: Path) -> tuple[Path, ...]:
    return (worker_dir / MORU_RESERVATION_FILENAME,)


def _check_no_symlink(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Symbolic link detected in path: {path}")


def is_isolated_worker_evidence(project: Path, evidence: Path) -> bool:
    """Return whether a path has the launcher-owned worker evidence shape."""

    project = project.expanduser().resolve()
    lexical_selected = evidence.expanduser().absolute()
    worker_root = project_state_dir_target(project) / "workers"
    try:
        _check_no_symlink(worker_root)
        _check_no_symlink(lexical_selected.parent)
        _check_no_symlink(lexical_selected)
        if worker_root.resolve() != worker_root:
            return False
        selected = lexical_selected.resolve()
        relative = selected.relative_to(worker_root)
    except (OSError, ValueError):
        return False
    return len(relative.parts) == 2 and relative.parts[-1] == "preflight.json"


def create_worker_reservation(worker_dir: Path) -> str:
    """Create a content-free reservation token in an already reserved directory."""

    _check_no_symlink(worker_dir)
    token = uuid.uuid4().hex
    marker_path = _reservation_paths(worker_dir)[0]
    try:
        with open(marker_path, "x", encoding="ascii") as marker:
            marker.write(token + "\n")
        try:
            os.chmod(marker_path, 0o600)
        except OSError:
            pass
    except FileExistsError as error:
        raise FileExistsError(f"reservation marker already exists: {marker_path}") from error
    return token


def worker_reservation_matches(worker_dir: Path, token: str) -> bool:
    """Validate a handoff-issued marker without following directory/file symlinks."""

    if len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
        return False
    try:
        _check_no_symlink(worker_dir)
    except OSError:
        return False
    return _matching_reservation_path(worker_dir, token) is not None


def _matching_reservation_path(worker_dir: Path, token: str) -> Path | None:
    for marker_path in _reservation_paths(worker_dir):
        try:
            recorded = marker_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if hmac.compare_digest(recorded, token):
            return marker_path
    return None


def claim_worker_reservation(worker_dir: Path, token: str) -> bool:
    """Atomically consume a valid reservation so only one worker can claim it."""

    try:
        _check_no_symlink(worker_dir)
    except OSError:
        return False
    if len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
        return False
    marker_path = _matching_reservation_path(worker_dir, token)
    if marker_path is None:
        return False
    claimed_path = marker_path.with_name(marker_path.name + "-claimed")
    try:
        marker_path.replace(claimed_path)
        recorded = claimed_path.read_text(encoding="ascii").strip()
        if not hmac.compare_digest(recorded, token):
            return False
        claimed_path.unlink()
        return True
    except (OSError, UnicodeDecodeError):
        return False


def isolated_worker_evidence(
    project: Path,
    parent_evidence: Path,
    requested: Path | None = None,
    *,
    lexical_project: Path | None = None,
    reserve: bool,
) -> Path:
    """Select or exclusively reserve a safe worker preflight path."""

    lexical_project = (lexical_project or project).expanduser().absolute()
    project = project.resolve()
    worker_root = project_state_dir_target(project) / "workers"
    lexical_worker_root = project_state_dir_target(lexical_project) / "workers"
    if worker_root.resolve() != worker_root:
        raise ValueError(
            "Fallback worker evidence root must not resolve through a symlink."
        )
    requested_path = (
        requested.expanduser().absolute()
        if requested
        else worker_root / uuid.uuid4().hex[:16] / "preflight.json"
    )
    try:
        try:
            relative = requested_path.relative_to(worker_root)
        except ValueError:
            relative = requested_path.relative_to(lexical_worker_root)
        selected = worker_root / relative
        selected.relative_to(project)
    except ValueError as error:
        raise ValueError(
            "Fallback worker evidence must stay under the project state workers directory."
        ) from error
    if len(relative.parts) != 2 or relative.parts[-1] != "preflight.json":
        raise ValueError(
            "Fallback worker evidence must use one opaque worker directory and preflight.json."
        )
    if selected == parent_evidence or (
        gate_evidence_path_for_preflight(selected)
        == gate_evidence_path_for_preflight(parent_evidence)
    ):
        raise ValueError(
            "Fallback worker evidence must not overlap parent evidence or ledger paths."
        )
    if reserve:
        worker_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if worker_root.resolve() != worker_root:
            raise ValueError(
                "Fallback worker evidence root must not resolve through a symlink."
            )
        try:
            selected.parent.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError as error:
            raise ValueError(
                "Fallback worker evidence directory must be newly and exclusively reserved."
            ) from error
        if selected.parent.resolve() != selected.parent:
            raise ValueError(
                "Fallback worker evidence directory must not resolve through a symlink."
            )
    return selected


def reserve_isolated_worker_evidence(
    project: Path,
    parent_evidence: Path,
    requested: Path | None = None,
    *,
    lexical_project: Path | None = None,
) -> tuple[Path, Path, str]:
    """Reserve one worker directory and mint its matching single-use token."""

    preflight = isolated_worker_evidence(
        project,
        parent_evidence,
        requested,
        lexical_project=lexical_project,
        reserve=True,
    )
    return (
        preflight,
        gate_evidence_path_for_preflight(preflight),
        create_worker_reservation(preflight.parent),
    )
