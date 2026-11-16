"""AST-only review context selection, with explicit unindexed-change reporting.

Owner: ReviewContext; allowed imports: ast and difflib from stdlib.
Forbidden: file reads, source execution, provider calls and Git operations.
Callers/tests: ReviewPacket; test_agent_review_packet exercises setters and budgets.
Verification: smallest definitions, direct helpers, unsupported context omissions.
"""
import ast
import difflib

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _index(text):
    try:
        found, queue = {}, [(ast.parse(text), "")]
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node, prefix in queue:
        for child in ast.iter_child_nodes(node):
            named = isinstance(child, (*_FUNCS, ast.ClassDef))
            if named:
                found.setdefault(prefix + child.name, child)
            queue.append((child, prefix + child.name + "." if named else prefix))
    return found


def _span(node):
    return min([node.lineno] + [item.lineno for item in node.decorator_list]), node.end_lineno


def _changed_defs(index, old, new):
    names, unindexed = [], False
    for tag, _, _, start, end in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for line in () if tag == "equal" else range(start + 1, end + 1) if end > start else (start, start + 1):
            spans = [(_span(node)[1] - _span(node)[0], name) for name, node in index.items()
                     if isinstance(node, _FUNCS) and _span(node)[0] <= line <= _span(node)[1]]
            if spans and min(spans)[1] not in names:
                names.append(min(spans)[1])
            if not spans:
                unindexed = True
    return names, unindexed


def _helpers(index, name):
    owner, found = name.rpartition(".")[0], []
    for call in ast.walk(index[name]):
        target = call.func if isinstance(call, ast.Call) else None
        if isinstance(target, ast.Attribute) and getattr(target.value, "id", None) in ("self", "cls"):
            callee = f"{owner}.{target.attr}"
        else:
            callee = getattr(target, "id", None)
        if callee != name and callee not in found and isinstance(index.get(callee), _FUNCS):
            found.append(callee)
    return found


def _section(rel, symbol, node, rows, role):
    start, end = _span(node)
    return {"path": rel, "symbol": symbol, "role": role, "start_line": start, "end_line": end, "lines": rows[start - 1:end]}


class ReviewContext:
    index = staticmethod(_index)
    changed_defs = staticmethod(_changed_defs)
    helpers = staticmethod(_helpers)
    section = staticmethod(_section)
