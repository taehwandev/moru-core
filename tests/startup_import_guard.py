"""Build argv for a fresh Python child that runs a script under an import tripwire.

The child installs a meta-path finder that raises ImportError for any blocked
module (exact name or a submodule). It also refuses to launch the script if a
blocked module is already in sys.modules, so a preloaded module cannot make the
proof vacuous. Names that the bootstrap itself needs (sys, os, runpy and their
import dependencies) cannot be proven absent and are reported as preloaded.

Limit: this gives functional evidence only (was the module imported at
startup?). The bootstrap adds interpreter and runpy overhead, so the command
must NOT be used for timings.
"""
import os

# Script path, blocked names and args reach the child only as argv data:
#   argv[1]=script, argv[2]=blocked count N, argv[3:3+N]=blocked, rest=script args.
_BOOTSTRAP = r'''
import os
import runpy
import sys
from importlib.abc import MetaPathFinder

script = os.path.realpath(sys.argv[1])
count = int(sys.argv[2])
blocked = tuple(sys.argv[3:3 + count])
args = sys.argv[3 + count:]


def is_blocked(fullname):
    return any(fullname == b or fullname.startswith(b + ".") for b in blocked)


preloaded = sorted(name for name in list(sys.modules) if is_blocked(name))
if preloaded:
    raise SystemExit("blocked modules already loaded before script: " + ", ".join(preloaded))


class _Tripwire(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if is_blocked(fullname):
            raise ImportError("blocked import: " + fullname)
        return None


sys.meta_path.insert(0, _Tripwire())
sys.path.insert(0, os.path.dirname(script))
sys.argv = [script, *args]
runpy.run_path(script, run_name="__main__")
'''


def guarded_command(executable, script, args, blocked):
    """Return argv (no shell, nothing spawned) running script under the guard."""
    names = list(blocked)
    for name in names:
        if not isinstance(name, str) or not name:
            raise ValueError("blocked names must be nonempty strings")
    extra = [str(a) for a in args]
    return [
        os.fspath(executable),
        "-c",
        _BOOTSTRAP,
        os.fspath(script),
        str(len(names)),
        *names,
        *extra,
    ]
