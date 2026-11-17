"""Owner: bounded named unittest selection. Allowed imports: stdlib only.
Forbidden: shell/provider calls, source execution before admission or receipts.
Callers/tests: verification hook and admitted runner; test_agent_unittest_selection.
Verification: scoped names, real selection, duplicate IDs and failed imports.
"""
import json
from pathlib import Path
import unittest
import sys
from importlib.machinery import EXTENSION_SUFFIXES, BYTECODE_SUFFIXES, SOURCE_SUFFIXES, ModuleSpec
from importlib.util import module_from_spec


def _present(path):
    try:
        path.lstat()
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False


def _check_prefix(directory, candidate):
    root = directory.resolve()
    exists = _present(candidate)
    if exists and candidate.is_dir() and not any(p.name == candidate.name for p in candidate.parent.iterdir()):
        raise ValueError('named test selectors require exact filesystem casing')
    if exists and not candidate.resolve().is_relative_to(root):
        raise ValueError('test selector directory escapes its test directory')
    sources = [Path(str(candidate) + suffix) for suffix in SOURCE_SUFFIXES]
    initializers = [candidate / ('__init__' + suffix) for suffix in SOURCE_SUFFIXES]
    for path in [*sources, *initializers]:
        if _present(path) and (not path.resolve().is_relative_to(root) or not path.is_file()):
            raise ValueError('test source or initializer escapes its test directory or is unavailable')
    modules = [path for path in sources if _present(path)]
    packages = [path for path in initializers if _present(path)]
    if modules and exists and candidate.is_dir() or len(modules) > 1 or len(packages) > 1:
        raise ValueError('test selector has ambiguous module and package sources')
    for suffix in (*BYTECODE_SUFFIXES, *EXTENSION_SUFFIXES):
        if _present(Path(str(candidate) + suffix)) or _present(candidate / ('__init__' + suffix)):
            raise ValueError('named test selection requires unambiguous Python source')
    return bool(modules or packages)


def _pin_namespaces(directory, names):
    # An earlier namespace portion does not outrank a later sys.path module.
    # Pin only the top-level namespace; import machinery binds nested children.
    for qualified in dict.fromkeys(name.split('.')[0] for name in names):
        path = directory / qualified
        if qualified not in sys.modules and path.is_dir() and not any(
                _present(path / ('__init__' + suffix)) for suffix in SOURCE_SUFFIXES):
            spec = ModuleSpec(qualified, loader=None, is_package=True)
            spec.submodule_search_locations = [str(path.resolve())]
            sys.modules[qualified] = module_from_spec(spec)


class UnittestSelection:
    PREFIX = '@selectors:'

    @classmethod
    def encode(cls, directory: Path, names) -> str:
        if not isinstance(names, list) or not 1 <= len(names) <= 64:
            raise ValueError('select 1 to 64 named tests')
        for name in names:
            if not isinstance(name, str) or len(name) > 240 or not all(p.isidentifier() for p in name.split('.')):
                raise ValueError('test selectors must be dotted Python identifiers')
            found = False
            parts = name.split('.')
            for end in range(1, len(parts) + 1):
                found = _check_prefix(directory, directory.joinpath(*parts[:end])) or found
            if not found:
                raise ValueError('test selector must resolve inside the selected test directory')
        return cls.PREFIX + json.dumps(list(dict.fromkeys(names)), separators=(',', ':'))

    @classmethod
    def load(cls, directory: Path, specification: str):
        names = json.loads(specification[len(cls.PREFIX):])
        cls.encode(directory, names)  # Validate again in the admitted child.
        for name in names:
            parts = name.split('.')
            for end in range(1, len(parts) + 1):
                module = sys.modules.get('.'.join(parts[:end]))
                if module is not None:
                    origin = getattr(module, '__file__', None)
                    origins = [origin] if isinstance(origin, str) else list(getattr(module, '__path__', ()))
                    if not origins or any(not Path(p).resolve().is_relative_to(directory.resolve()) for p in origins):
                        raise ValueError('test selector conflicts with a module loaded outside its test directory')
        _pin_namespaces(directory, names)
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        unique, seen = unittest.TestSuite(), set()
        def visit(group):
            for test in group:
                if isinstance(test, unittest.TestSuite):
                    visit(test)
                elif test.id() not in seen:
                    seen.add(test.id())
                    unique.addTest(test)
        visit(suite)
        return unique
