"""Owner: bounded AST-only local call contracts and constant declarations.
Allowed imports: stdlib AST/path/copy; guarded source is supplied by the caller.
Forbidden: source imports/evaluation, providers, Git and filesystem writes.
Callers/tests: ReviewPacket; test_agent_review_packet_contracts.
Verification: static signatures, referenced constants, privacy and no recursion.
"""
import ast
import copy
import re
from pathlib import Path


def _redact(node):
    result = copy.deepcopy(node)
    for child in ast.walk(result):
        if isinstance(child, ast.Constant) and isinstance(child.value, (str, bytes)):
            child.value = b'<redacted literal>' if isinstance(child.value, bytes) else '<redacted literal>'
        if isinstance(child, ast.keyword) and child.arg and re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', child.arg, re.I):
            child.value = ast.Constant('<redacted literal>')
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [*child.args.posonlyargs, *child.args.args]
            for index, arg in enumerate(args[len(args) - len(child.args.defaults):]):
                if re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', arg.arg, re.I):
                    child.args.defaults[index] = ast.Constant('<redacted literal>')
            for index, arg in enumerate(child.args.kwonlyargs):
                if child.args.kw_defaults[index] is not None and re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', arg.arg, re.I):
                    child.args.kw_defaults[index] = ast.Constant('<redacted literal>')
    return result


def _local_sources(root, rel, module, level):
    base = Path(rel).parent
    if level:
        if level - 1 > len(base.parts):
            return []
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        bases = [base, Path('.')]
    paths = []
    for parent in bases:
        target = parent.joinpath(*module.split('.'))
        for candidate in (target.with_suffix('.py'), target / '__init__.py'):
            if (not candidate.is_absolute() and '..' not in candidate.parts
                    and (Path(root) / candidate).is_file() and candidate.as_posix() not in paths):
                paths.append(candidate.as_posix())
    return paths


def _module_import_bindings(tree):
    names, wildcard, pending = set(), False, list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                wildcard |= alias.name == '*'
                names.add(alias.asname or alias.name.split('.')[0])
        else:
            pending.extend(ast.iter_child_nodes(node))
    return names, wildcard


def _contract_index(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None, {}
    index, queue = {}, [(tree, '')]
    for node, prefix in queue:
        for child in ast.iter_child_nodes(node):
            named = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            if named:
                key = prefix + child.name
                index[key] = child if key not in index else None
            queue.append((child, prefix + child.name + '.' if named else prefix))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            for name in ast.walk(target) if isinstance(target, (ast.Name, ast.Tuple, ast.List)) else ():
                if isinstance(name, ast.Name):
                    index[name.id] = node if name.id not in index else None
    for root in tree.body:
        if isinstance(root, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for node in ast.walk(root):
            names = ([node.id] if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                     else [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else [])
            for name in names:
                index[name] = None
    imports, wildcard = _module_import_bindings(tree)
    if wildcard:
        return tree, {'*': None}
    for name in imports.intersection(index):
        index[name] = None
    return tree, index


class ReviewContracts:
    @staticmethod
    def _section(rel, symbol, node, text):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = copy.copy(node)
            signature.body, signature.decorator_list = [ast.Pass()], []
            rendered = ast.unparse(_redact(signature)).rsplit('\n', 1)[0]
            decorators = [ast.unparse(_redact(d)) for d in node.decorator_list]
            if len(rendered.encode()) + sum(len(d.encode()) for d in decorators) > 4096:
                return None
            return dict(path=rel, symbol=symbol, role='call_contract', rendering='ast_signature',
                        start_line=node.lineno, end_line=node.end_lineno, signature=rendered,
                        decorators=decorators)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            if any(re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name, re.I) for name in names):
                return None
            value = node.value
            if value is None or any(isinstance(n, (ast.Call, ast.Attribute, ast.Lambda, ast.Await)) for n in ast.walk(value)):
                return None
            lines = ast.unparse(_redact(node)).splitlines()
            if len('\n'.join(lines).encode()) <= 4096:
                return dict(path=rel, symbol=symbol, role='constant_declaration', rendering='redacted_ast',
                            start_line=node.lineno, end_line=node.end_lineno, lines=lines)
        return None

    @classmethod
    def collect(cls, root, rel, text, symbols, read_source):
        tree, index = _contract_index(text)
        sections, omissions, imports, references, seen = [], [], {}, [], set()
        if tree is None:
            return sections, omissions
        if '*' in index:
            return sections, [dict(kind='contract', path=rel, reason='wildcard_import_requires_explicit_context')]
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module, alias.name, node.level)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname or '.' not in alias.name:
                        imports[alias.asname or alias.name] = (alias.name, '', 0)
        for name in symbols:
            if name not in index or index[name] is None:
                continue
            nodes = list(ast.walk(index[name]))
            shadowed = {n.arg for n in nodes if isinstance(n, ast.arg)}
            shadowed |= {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            shadowed |= {a.asname or a.name.split('.')[0] for n in nodes
                         if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            shadowed |= {n.name for n in nodes if isinstance(n, ast.ExceptHandler) and n.name}
            shadowed |= {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not index[name]}
            shadowed |= {s for n in nodes if isinstance(n, (ast.Global, ast.Nonlocal)) for s in n.names}
            shadowed |= {getattr(n, 'name', None) or getattr(n, 'rest', None) for n in nodes
                         if type(n).__name__ in ('MatchAs', 'MatchStar', 'MatchMapping')}
            for node in nodes:
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in shadowed:
                    references.append((node.id, ''))
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id not in shadowed:
                    references.append((node.value.id, node.attr))
        for name, attribute in dict.fromkeys(references):
            if len(seen) >= 32:
                omissions.append(dict(kind='contract', path=rel, reason='contract_count_budget'))
                break
            target_rel, symbol, source = rel, name, text
            if name in imports and name in index:
                continue  # Rebound module names cannot be resolved statically here.
            if name in imports:
                module, imported, level = imports[name]
                if not imported and not attribute:
                    continue
                symbol = '.'.join(part for part in (imported, attribute) if part)
                candidates = _local_sources(root, rel, module, level)
                if len(candidates) != 1:
                    if candidates:
                        omissions.append(dict(kind='contract', path=rel, symbol=name, reason='ambiguous_local_import'))
                    continue  # Only unambiguous repository-local imports are auto-read.
                target_rel = candidates[0]
                try:
                    source = read_source(target_rel)
                except (OSError, ValueError):
                    omissions.append(dict(kind='contract', path=target_rel, symbol=symbol, reason='guarded_source_unavailable'))
                    continue
                _, target_index = _contract_index(source)
                parts = symbol.split('.')
                node = (target_index.get(symbol) if all(target_index.get('.'.join(parts[:end])) is not None
                        for end in range(1, len(parts) + 1)) else None)
            else:
                node = index.get(symbol)
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
            identity = (target_rel, symbol)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                section = cls._section(target_rel, symbol, node, source) if node is not None else None
            except RecursionError:
                section = None
            if section:
                sections.append(section)
            else:
                omissions.append(dict(kind='contract', path=target_rel, symbol=symbol, reason='explicit_context_required'))
        return sections, omissions
