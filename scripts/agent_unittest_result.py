"""Run unittest discovery and write its result to a separate local receipt."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path



class _ProofResult(unittest.TextTestResult):
    def __init__(self, *args, selected_names=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.current_test = None
        self.skipped_methods = 0
        self.passed_ids = []
        self.failed_ids = []
        self.recorded_id_bytes = 0
        self.ids_complete = True
        self.selected_names = selected_names
        self.passed_selectors, self.failed_selectors = set(), set()

    def _record_id(self, target, test):
        value = test.id()
        observed = self.passed_selectors if target is self.passed_ids else self.failed_selectors
        observed.update(name for name in self.selected_names if value == name or value.startswith(name + '.'))
        size = len(value.encode('utf-8'))
        if size > 512 or self.recorded_id_bytes + size > 65536 or len(target) >= 1024:
            self.ids_complete = False
        else:
            target.append(value)
            self.recorded_id_bytes += size

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record_id(self.passed_ids, test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record_id(self.failed_ids, test)

    def addError(self, test, err):
        super().addError(test, err)
        self._record_id(self.failed_ids, test)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record_id(self.failed_ids, test)

    def startTest(self, test):
        super().startTest(test)
        self.current_test = test

    def stopTest(self, test):
        super().stopTest(test)
        self.current_test = None

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        # Skipped subtests are separate objects, not skipped whole methods.
        if test is self.current_test:
            self.skipped_methods += 1


def _without_moru_scripts(entries: list[str]) -> list[str]:
    """Drop Moru's own script directories from the project's import path.

    Python puts this runner's directory first, so a project test importing a
    module the project lacks would otherwise import Moru's same-named module
    and could pass against the wrong code. The runner needs only the standard
    library, already imported above.
    """
    scripts = Path(__file__).resolve().parent
    own = {scripts, scripts / "support"}
    return [entry for entry in entries if Path(entry or ".").resolve() not in own]


def main() -> int:
    # A loop parent records this process group before releasing project code.
    # Parent death before admission closes the pipe and cannot start tests.
    if os.environ.pop("MORU_UNITTEST_ADMISSION", None) == "1":
        if sys.stdin.buffer.read(1) != b"\x01":
            return 125
        # Preserve the selected interpreter's normal startup/environment, now
        # inside the admitted PID and group. The isolated bootstrap loaded no
        # project-controlled interpreter or startup hooks before this point.
        os.execv(sys.argv[1], sys.argv[1:])
    from agent_unittest_selection import UnittestSelection
    project, directory, pattern, receipt = sys.argv[1:5]
    sys.path[:] = [str(Path(directory).resolve()), str(Path(project).resolve()), *_without_moru_scripts(sys.path)]
    suite = (UnittestSelection.load(Path(directory), pattern) if pattern.startswith(UnittestSelection.PREFIX)
             else unittest.defaultTestLoader.discover(start_dir=directory, pattern=pattern))
    selected = json.loads(pattern[len(UnittestSelection.PREFIX):]) if pattern.startswith(UnittestSelection.PREFIX) else []
    result = unittest.TextTestRunner(resultclass=lambda *a, **kw:
        _ProofResult(*a, selected_names=selected, **kw)).run(suite)
    executed = result.testsRun - result.skipped_methods - len(result.expectedFailures)
    Path(receipt).write_text(
        json.dumps({"tests_run": result.testsRun,
                    "successful": result.wasSuccessful() and executed > 0,
                    "passed_ids": result.passed_ids, "failed_ids": result.failed_ids,
                    "passed_selectors": sorted(result.passed_selectors),
                    "failed_selectors": sorted(result.failed_selectors),
                    "ids_complete": result.ids_complete}),
        encoding="utf-8",
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
