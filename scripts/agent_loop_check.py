"""Execute frozen loop checks using Moru's bounded unittest runner.

Owner: LoopCheck; allowed imports: loop input contract and unittest executor.
Forbidden imports: model, shell, source-write or gate-ledger adapters.
Caller: agent_loop_state; verification: test_agent_loop_check.
"""

from __future__ import annotations

import fnmatch
import json
import math
import os
import stat
import uuid
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING

from agent_verification_hook import execute_unittest, unittest_command

if TYPE_CHECKING:
    from agent_loop_inputs import LoopInputs


class LoopCheck:
    """Observe regression, goal and optional measurement without writing source."""

    def __init__(self, project: Path, config: dict, artifacts_dir: Path,
                 process_admission=None):
        self.project = project.resolve()
        self.config = dict(config)
        self.artifacts_dir = artifacts_dir
        self.process_admission = process_admission

    def validate(self, inputs: LoopInputs) -> None:
        """Reject unusable immutable selections before enrolling their contract."""
        self._commands(1)
        if not all(self._validate_selection(inputs).values()):
            raise ValueError("both loop selections require frozen Python test files")

    def run(self, inputs: LoopInputs, timeout: float) -> dict:
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or timeout <= 0):
            raise ValueError("loop check timeout must be finite and positive")
        deadline = monotonic() + timeout
        before = inputs.capture()
        commands = self._commands(timeout)
        selected = self._validate_selection(inputs)
        measurement, descriptor = (_measurement_path(self.project, self.artifacts_dir)
                                   if self.config.get("metric") is not None else (None, None))
        try:
            environment = {"MORU_LOOP_MEASUREMENT_PATH": str(measurement)} if measurement else None
            regression = self._execute(commands["regression"], deadline, environment, selected["regression"])
            if self.config["goal_pattern"] == self.config["regression_pattern"]:
                goal = dict(regression)
            else:
                # Remove only our own artifact, using its retained directory
                # descriptor even if a test replaced a pathname with a link.
                if measurement is not None:
                    try:
                        os.unlink(measurement.name, dir_fd=descriptor)
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        raise ValueError("invalid current loop measurement artifact") from error
                selected = self._validate_selection(inputs)
                goal = self._execute(commands["goal"], deadline, environment, selected["goal"])
            after = inputs.capture()
            value = _measurement_value(measurement, descriptor) if measurement else None
            return {"before": before, "after": after, "regression": regression,
                    "goal": goal, "value": value, "stable": before == after}
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _commands(self, timeout: float) -> dict:
        directory = self.config.get("directory")
        if (not isinstance(directory, str) or not directory
                or Path(directory).is_absolute() or ".." in Path(directory).parts):
            raise ValueError("loop test directory must be project-relative")
        return {kind: unittest_command(SimpleNamespace(
            project=self.project, test_directory=directory,
            test_pattern=self.config.get(f"{kind}_pattern"), verify_timeout=timeout))
            for kind in ("regression", "goal")}

    def _validate_selection(self, inputs: LoopInputs) -> dict:
        if inputs.project != self.project:
            raise ValueError("loop check inputs must belong to the checked project")
        directory = self.project
        for part in Path(self.config["directory"]).parts:
            directory /= part
            if directory.is_symlink():
                raise ValueError("selected tests contain a symlink directory")
        if not directory.is_dir():
            raise ValueError("selected test directory is unavailable")
        frozen = set(inputs.verifiers)
        selected = {"regression": 0, "goal": 0}
        for parent, directories, files in os.walk(directory, followlinks=False):
            # unittest follows package directories through symlinks; never let
            # such a package hide an executable selection from the frozen set.
            if any((Path(parent) / name).is_symlink() for name in directories):
                raise ValueError("selected tests contain a symlink directory")
            for name in files:
                kinds = [kind for kind in selected
                         if fnmatch.fnmatchcase(name, self.config[f"{kind}_pattern"])]
                if not kinds:
                    continue
                path = Path(parent) / name
                relative = path.relative_to(self.project).as_posix()
                if path.is_symlink() or not path.is_file() or relative not in frozen:
                    raise ValueError(f"selected test is not a frozen verifier: {relative}")
                for kind in kinds:
                    selected[kind] += 1
        return selected

    def _execute(self, command: list[str], deadline: float, environment: dict | None,
                 selected: int) -> dict:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return {"exit": 124, "tests": 0, "passed": False}
        if not selected:
            return {"exit": 0, "tests": 0, "passed": False}
        code, count, passed = execute_unittest(
            command, self.project, remaining, extra_env=environment,
            process_admission=self.process_admission)
        valid = type(code) is int and type(count) is int and count >= 0 and type(passed) is bool
        if not valid:
            raise ValueError("invalid observed unittest result")
        return {"exit": code, "tests": count, "passed": code == 0 and passed and count > 0}


def _measurement_path(project: Path, artifacts_dir: Path) -> tuple[Path, int]:
    directory = artifacts_dir if artifacts_dir.is_absolute() else project / artifacts_dir
    try:
        relative = directory.relative_to(project)
        if ".." in relative.parts:
            raise ValueError("artifact directory must remain inside the project")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(project, flags)
        try:
            for part in relative.parts:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                nested = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = nested
            name = f"check-{uuid.uuid4().hex}"
            os.mkdir(name, mode=0o700, dir_fd=descriptor)
            child = os.open(name, flags, dir_fd=descriptor)
            return directory / name / "measurement.json", child
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:
        raise ValueError("loop artifact directory must be real and inside the project") from error


def _measurement_value(path: Path, directory: int) -> int | float:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate measurement key")
            result[key] = value
        return result

    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                raise ValueError("measurement must be a bounded regular file")
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("measurement exceeds size limit")
        result = json.loads(raw, object_pairs_hook=unique_keys)
        if not isinstance(result, dict) or set(result) != {"value"}:
            raise ValueError("measurement must contain only value")
        value = result["value"]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("measurement value must be finite numeric data")
        return value
    except (OSError, ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"invalid current loop measurement: {error}") from error
