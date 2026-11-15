"""Run real worker regressions in the declared inherited bootstrap profile.

The CLI still loads repository tests through PYTHONPATH=scripts:tests. Once
Python initialized that import path, owned fixture guardians need no executable
startup overrides. Unknown overrides/customizers have separate rollback tests.
"""
import os
from pathlib import Path
import runpy
import sys
import tempfile


def main():
    if sys.argv[1:3] != ['-m', 'unittest']:
        raise SystemExit('expected -m unittest followed by test selectors')
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'scripts'), str(root / 'tests')]
    safe = {'PYTHONUTF8', 'PYTHONCOERCECLOCALE', 'PYTHONDONTWRITEBYTECODE', 'PYTHONNOUSERSITE'}
    for name in list(os.environ):
        if ((name.startswith(('PYTHON', '_PYTHON')) and name not in safe)
                or name.startswith(('MORU_', 'GIT_', 'CODEX_', 'CLAUDE_', 'AGY_', 'ANTIGRAVITY_', 'SPILL_'))):
            os.environ.pop(name)
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    with tempfile.TemporaryDirectory(prefix='native-dispatch-session-') as temporary:
        base = Path(temporary)
        (base / 'home').mkdir()
        os.environ.update(HOME=str(base / 'home'), MORU_STATE_HOME=str(base / 'state'),
                          MORU_HOME=str(root), MORU_LAUNCHER_BACKEND='auto')
        sys.argv = ['unittest', *sys.argv[3:]]
        runpy.run_module('unittest', run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
