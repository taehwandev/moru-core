"""Embed a bounded runtime source snapshot; never import policy."""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unicodedata


def _policy_tree(path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return ast.Module(body=[], type_ignores=[])


def _policy_data_call(tree, evaluate):
    """Reject executable calls receiving mutable data, including simple aliases."""
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            pending.extend(getattr(node, "decorator_list", []))
            pending.extend(node.args.defaults)
            pending.extend(value for value in node.args.kw_defaults if value is not None)
            continue
        if isinstance(node, ast.Call):
            try:
                evaluate(node, set())  # Closed data constructors are safe.
            except (ValueError, TypeError, ZeroDivisionError, RecursionError):
                for child in ast.walk(node):
                    if not isinstance(child, ast.Name):
                        continue
                    try:
                        if type(evaluate(child, set())) is set:
                            return True
                    except (ValueError, TypeError, ZeroDivisionError, RecursionError):
                        pass
        pending.extend(ast.iter_child_nodes(node))
    return False


def _policy_constants(tree):
    """Closed data evaluator; never import, execute or evaluate policy code."""
    definitions = {}
    shadowed_frozenset = any(
        isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "frozenset"
        or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "frozenset"
        or isinstance(node, ast.alias) and (node.asname or node.name) == "frozenset"
        for node in ast.walk(tree)
    )
    direct_targets = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
            direct_targets.add(node.targets[0])
            definitions[name] = value if name not in definitions else None
    # A later/nonliteral binding must not leave a stale earlier constant active.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node not in direct_targets:
            definitions[node.id] = None
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = None
        elif isinstance(node, ast.alias):
            definitions[node.asname or node.name.split(".")[0]] = None

    def evaluate(node, visiting):
        if len(visiting) > 32:
            raise ValueError("constant dependency bound")
        if isinstance(node, ast.Constant) and type(node.value) in (int, str):
            return node.value
        if isinstance(node, ast.Name) and node.id not in visiting:
            return evaluate(definitions.get(node.id), visiting | {node.id})
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand, visiting)
            if type(value) is int:
                return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Set):
            result = set()
            for item in node.elts:
                if isinstance(item, ast.Starred):
                    expanded = evaluate(item.value, visiting)
                    if type(expanded) is not set:
                        raise ValueError("non-set expansion")
                    result.update(expanded)
                else:
                    result.add(evaluate(item, visiting))
            return result
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "frozenset" and not shadowed_frozenset
                and len(node.args) == 1 and not node.keywords):
            value = evaluate(node.args[0], visiting)
            if type(value) is set:
                return value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)):
            left, right = evaluate(node.left, visiting), evaluate(node.right, visiting)
            if type(left) is int and type(right) is int:
                if max(left.bit_length(), right.bit_length()) > 128:
                    raise ValueError("integer bound")
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left // right
        raise ValueError("unsupported policy data")

    if _policy_data_call(tree, evaluate):
        return lambda name: None

    def read(name):
        try:
            value = evaluate(definitions.get(name), {name})
            return sorted(value) if type(value) is set else value
        except (ValueError, TypeError, ZeroDivisionError, RecursionError):
            return None
    return read


def _policy_path(tree, name, left):
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(functions) != 1:
        return None
    node = functions[0]
    args = node.args
    if (not isinstance(node, ast.FunctionDef) or node.decorator_list or args.posonlyargs
            or len(args.args) != 1 or args.args[0].arg != "project" or args.defaults
            or args.kwonlyargs or args.vararg or args.kwarg or len(node.body) != 1):
        return None
    statement = node.body[0]
    value = statement.value if isinstance(statement, ast.Return) else None
    if (not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Div)
            or ast.dump(value.left) != ast.dump(ast.parse(left, mode="eval").body)):
        return None
    return value.right


def emit_retention_policy(root, output):
    """Emit only canonical constants and verified simple project path shapes."""
    evidence = _policy_tree(root / "scripts/agent_run_evidence.py")
    states = _policy_tree(root / "scripts/agent_run_states.py")
    global_state = _policy_tree(root / "scripts/support/global_state.py")
    read = _policy_constants(evidence)
    policy = {"schema_version": 1}
    names = {"run_id_length": "RUN_ID_LENGTH", "registry_schema_version": "REGISTRY_SCHEMA_VERSION",
             "keep": "DEFAULT_KEEP", "abandoned_after_seconds": "DEFAULT_ABANDONED_AFTER_SECONDS",
             "orphan_after_seconds": "DEFAULT_ORPHAN_AFTER_SECONDS", "holding_states": "CLAIM_HOLDING_STATES",
             "settled_states": "SETTLED_STATES", "finished_phases": "FINISHED_PHASES"}
    policy.update({key: read(name) for key, name in names.items()})
    policy["run_states"] = _policy_constants(states)("RUN_STATES")
    state_path = _policy_path(global_state, "project_state_dir_target", "project")
    policy["state_dir"] = (_policy_constants(global_state)("STATE_DIR_NAME")
                           if isinstance(state_path, ast.Name) and state_path.id == "STATE_DIR_NAME" else None)
    run_path = _policy_path(evidence, "runs_dir", "project_state_dir_target(project)")
    policy["runs_dir"] = run_path.value if isinstance(run_path, ast.Constant) and type(run_path.value) is str else None
    output.write_text(json.dumps(policy, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")


def emit_argparse_contract():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--source-root")
    parser.add_argument("--remote-check", action="store_true")
    patterns = {r"^-\d+$|^-\d*\.\d+$": "full", r"-\.?\d": "prefix"}
    pattern = parser._negative_number_matcher.pattern
    if pattern not in patterns:
        raise RuntimeError("unsupported argparse negative-number pattern: " + pattern)

    def outcome(args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(args)
            except SystemExit as error:
                return error.code
            except IndexError:
                return "IndexError"
        return "parsed"

    observed = tuple(outcome([arg]) for arg in ("-hfoo", "-hhfoo", "-h=foo", "-h=", "-h=h", "-hh=foo", "--help=foo"))
    modes = {(2, 2, 2, "IndexError", 0, 2, 2): "legacy", (0, 0, 2, 2, 2, 2, 2): "eager"}
    if observed not in modes:
        raise RuntimeError("unsupported argparse short-help behavior: " + repr(observed))
    ambiguity = outcome(["--help", "--=x"])
    if ambiguity not in (0, 2):
        raise RuntimeError("unsupported argparse ambiguity ordering: " + repr(ambiguity))
    print("cargo:rustc-env=MORU_ARGPARSE_SHORT_HELP=" + modes[observed])
    print("cargo:rustc-env=MORU_ARGPARSE_NEGATIVE_NUMBER=" + patterns[pattern])
    print("cargo:rustc-env=MORU_ARGPARSE_AMBIGUITY=" + ("prescan" if ambiguity == 2 else "sequential"))


def emit_python_text(output):
    """Bind text semantics to the artifact builder's Unicode database.

    Digest order per valid scalar: repr UTF-8, LF, then three raw boolean
    bytes in printable/decimal/whitespace order, then decimal value or 255.
    Surrogates are excluded.
    """
    ranges = [[], [], []]
    starts = [None, None, None]
    digest = hashlib.sha256()
    for codepoint in range(0x110000):
        scalar = not 0xD800 <= codepoint <= 0xDFFF
        text = chr(codepoint)
        flags = (
            (text.isprintable(), text.isdecimal(), text.isspace())
            if scalar else (False, False, False)
        )
        for index, enabled in enumerate(flags):
            if enabled and starts[index] is None:
                starts[index] = codepoint
            elif not enabled and starts[index] is not None:
                ranges[index].append((starts[index], codepoint - 1))
                starts[index] = None
        if scalar:
            digit = unicodedata.decimal(text, 255)
            if flags[1]:
                assert digit == (codepoint - starts[1]) % 10
            digest.update(repr(text).encode("utf-8"))
            digest.update(b"\n")
            digest.update(bytes(flags))
            digest.update(bytes([digit]))
    for index, start in enumerate(starts):
        if start is not None:
            ranges[index].append((start, 0x10FFFF))
    rows = [
        "// Generated by pretool_contract.py; artifact-build Python semantics.",
        f"#[cfg(test)] const UNICODE_VERSION: &str = {json.dumps(unicodedata.unidata_version)};",
        f"#[cfg(test)] const SCALAR_GOLDEN_SHA256: &str = {json.dumps(digest.hexdigest())};",
    ]
    for name, entries in zip(("PRINTABLE", "DECIMAL", "WHITESPACE"), ranges):
        rows.append(f"const {name}: &[(u32, u32)] = &[")
        rows.extend(f"    (0x{start:x}, 0x{end:x})," for start, end in entries)
        rows.append("];")
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _resume_flush_error():
    incoming, outgoing = os.pipe()
    os.close(incoming)
    try:
        done = subprocess.run([sys.executable, "-S", "-c",
            "import sys;sys.stdout.write('x');sys.exit(2)"], stdin=subprocess.DEVNULL,
            stdout=outgoing, stderr=subprocess.PIPE, timeout=5)
        return done.stderr.decode("utf-8") if done.returncode == 120 else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    finally:
        os.close(outgoing)


def emit(output):
    emit_argparse_contract()
    emit_python_text(output.parent / "python_text_contract.rs")
    from memory_contract import emit as emit_memory
    emit_memory(output.parent / "memory_contract.rs")
    print("cargo:rerun-if-changed=memory_contract.py")
    # Preserve the artifact builder's argparse wording without a runtime Python
    # subprocess. Python 3.9 says "optional arguments", newer versions "options".
    title = argparse.ArgumentParser()._optionals.title
    print("cargo:rustc-env=MORU_ARGPARSE_OPTIONS_TITLE=" + title + ":")
    integer_limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
    print("cargo:rustc-env=MORU_PYTHON_INT_MAX_STR_DIGITS=" + str(integer_limit))
    integer_error = ""
    if 0 < integer_limit <= 100_000:
        try:
            int("1" * (integer_limit + 1))
        except ValueError as error:
            message = str(error)
            count = str(integer_limit + 1)
            if message.count(count) == 1:
                integer_error = message.replace(count, "<count>")
    print("cargo:rustc-env=MORU_PYTHON_INT_LIMIT_ERROR=" + integer_error)
    print("cargo:rustc-env=MORU_PYTHON_FLUSH_ERROR_JSON=" + json.dumps(_resume_flush_error()))
    print("cargo:rustc-env=MORU_PYTHON_IO_BUFFER=" + str(io.DEFAULT_BUFFER_SIZE))
    print("cargo:rustc-env=MORU_PYTHON_IO_CHUNK=" + str(sys.stdout._CHUNK_SIZE))
    print("cargo:rustc-env=MORU_PYTHON_DEFAULT_PATH=" + os.defpath)
    root = Path(__file__).resolve().parents[2]
    emit_retention_policy(root, output.parent / "retention_policy.json")
    sys.path.insert(0, str(root / "scripts"))
    from support.native_source_inputs import CACHE_DIRECTORIES, pretool_contract
    sources, directories = pretool_contract(root)
    rows = ["pub(super) const SOURCES: &[(&str, &[u8], u64)] = &["]
    rows.extend(f"({json.dumps(path, ensure_ascii=False)}, &{list(digest)}, {size})," for path, (digest, size) in sources.items())
    rows.append("];")
    rows.append("pub(super) const DIRECTORIES: &[&str] = &[")
    rows.extend(json.dumps(path, ensure_ascii=False) + "," for path in directories)
    rows.append("];")
    rows.append("pub(super) const CACHES: &[&str] = &[")
    rows.extend(json.dumps(name) + "," for name in sorted(CACHE_DIRECTORIES))
    rows.append("];")
    output.write_text("\n".join(rows) + "\n")
    print("cargo:rerun-if-changed=" + str(root / "scripts/support/native_source_inputs.py"))
    for path in (*sources, *directories):
        print("cargo:rerun-if-changed=" + str(root / path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
