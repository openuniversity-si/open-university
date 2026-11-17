"""Consumer demands and per-adapter behavioral evidence at the forge boundary (D-285, C3).

Declarations are not inferred from implementations. The AST confrontation exposes
missing/stale consumers and evidence; runtime checks never import or execute tests.
The static floor and unknowns are those of operation_relations, not a call graph. The confrontation with the
tree (confront, report, the command line) reads operation_relations, a module of the planning layer, so it is
scripts/lib/operation_demands_check.py (D-322); this module keeps the runtime refusal the events port calls.
"""
import ast
import python_source
from functools import cache
import json
import re
from pathlib import Path
import sys
import os
import weakref

ROOT = Path(__file__).resolve().parent.parent.parent
DECLARATION = 'scripts/lib/operation_demands.json'
# The port and its adapters by name (D-322: here, in the events layer, so the runtime refusal imports nothing of the
# planning layer; operation_relations re-exports them for its census).
PORT = 'scripts/lib/forge_events.py'
ADAPTER_MODULES = {
    'origin': ('scripts/lib/forge_origin.py', 'OriginAdapter'),
    'file': ('scripts/lib/forge_events.py', 'FileAdapter'),
    'git-ref': ('scripts/lib/forge_git_ref.py', 'GitRefs'),
}
_INTERNAL_FILES = frozenset((Path(__file__).resolve(), Path(__file__).with_name('forge_events.py').resolve()))
_origins = {}  # code identity -> (weak code reference, canonical origin); unloaded code retains no entry
_ADAPTER_NAMES = {(Path(module).stem, holder): name
                  for name, (module, holder) in ADAPTER_MODULES.items()}
_ADAPTER_NAMES.update({('forge_events', 'MemoryAdapter'): 'memory', ('forge_git_ref', 'GitRefAdapter'): 'git-ref'})
_ADAPTER_NAMES[('forge_origin', 'ObservedAdapter')] = 'origin'  # PR-OBSERVATION: Origin's own answers, replayed


def _code_origin(code):
    """Bind loaded absolute code to its origin once. Relative synthetic code keeps its caller's cwd semantics."""
    filename = code.co_filename
    if not os.path.isabs(filename):
        return Path(filename).resolve()
    identity = id(code)
    held = _origins.get(identity)
    if held is not None and held[0]() is code:
        return held[1]
    origin = Path(filename).resolve()

    def unloaded(reference, origins=_origins):
        current = origins.get(identity)
        if current is not None and current[0] is reference:
            origins.pop(identity, None)

    _origins[identity] = (weakref.ref(code, unloaded), origin)
    return origin


class CompatibilityError(RuntimeError):
    """A required operation has no compatibility evidence for the selected adapter."""


@cache
def load(root=None):
    """Read demands by consumer and evidence by adapter/operation; no configuration store."""
    base = Path(root) if root is not None else ROOT
    try:
        document = json.loads((base / DECLARATION).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise CompatibilityError(f'cannot read compatibility declaration: {error}') from None
    for field in ('consumers', 'proofs'):
        if not isinstance(document.get(field), dict):
            raise CompatibilityError(f'compatibility declaration has no {field} mapping')
    for consumer, operations in document['consumers'].items():
        if not isinstance(operations, list) or not operations or any(not isinstance(op, str) for op in operations):
            raise CompatibilityError(f'{consumer}: demand must name required operations')
        if len(operations) != len(set(operations)):
            raise CompatibilityError(f'{consumer}: duplicate required operation')
    for adapter, proofs in document['proofs'].items():
        if not isinstance(proofs, dict) or any(not isinstance(ref, str) or not re.fullmatch(r'[^:]+::[^:]+::test_\w+', ref)
                                               for ref in proofs.values()):
            raise CompatibilityError(f'{adapter}: evidence must name file::class::test')
    return document


def callers(root=None):
    """Active repository consumers, including ancestors of a shared factory/port.

    Unrecognized repository paths remain in the result; they are exposed as
    unknown, not silently treated as consumers with an empty proven demand.
    """
    base = Path(root) if root is not None else ROOT
    frame, found = sys._getframe(1), []
    try:
        while frame is not None:
            path = _code_origin(frame.f_code)
            if path in _INTERNAL_FILES:
                frame = frame.f_back
                continue
            try:
                relative = path.relative_to(base).as_posix()
            except ValueError:
                found.append(f'unknown consumer: {path}')
                break
            if (relative and relative not in (DECLARATION, PORT, 'scripts/lib/operation_demands.py')
                    and relative not in found):
                found.append(relative)
                if relative not in load(base)['consumers']:
                    break  # a journal-only helper owns this call, not its caller's forge demand
            frame = frame.f_back
    finally:
        del frame
    return found


def adapter_name(adapter):
    """Concrete type identity, never a duck-typed method or an adapter's self-assertion."""
    cls = type(adapter)
    return _ADAPTER_NAMES.get((cls.__module__, cls.__name__), f'unknown:{cls.__module__}.{cls.__name__}')


def requirements(consumers, document=None):
    document = load() if document is None else document
    return [(consumer, operation) for consumer in consumers
            for operation in document['consumers'].get(consumer, [])]


def refusals(adapter, consumers, document=None, root=None):
    document = load() if document is None else document
    proofs = document['proofs'].get(adapter, {})
    return [(consumer, operation) for consumer, operation in requirements(consumers, document) if not proofs.get(operation)
            or not _evidence(Path(root) if root is not None else ROOT, proofs[operation], operation)]


def require(adapter, consumers, operation=None, document=None):
    """Refuse the whole declared demand before resolving/invoking any adapter method."""
    document = load() if document is None else document
    consumers = list(consumers)
    missing = refusals(adapter, consumers, document)
    reference = document['proofs'].get(adapter, {}).get(operation)
    if operation and (not reference or not _evidence(ROOT, reference, operation)):
        missing.append((next(iter(consumers), 'unknown consumer'), operation))
    if missing:
        detail = '; '.join(f'operation {op}, adapter {adapter}, demand {consumer}: has no {op} operation with compatibility proof'
                           for consumer, op in sorted(set(missing)))
        raise CompatibilityError(detail)


@cache
def _evidence(base, reference, operation):
    """Resolve a real inherited test which calls this operation, without importing its fixture."""
    path, holder, method = reference.split('::')
    try:
        tree = python_source.parse((base / path).read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return False
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def resolve(name, visited):
        if name in visited or name not in classes:
            return None
        visited.add(name)
        cls = classes[name]
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == method:
                return node
        for parent in cls.bases:
            if isinstance(parent, ast.Name):
                found = resolve(parent.id, visited)
                if found is not None:
                    return found
        return None

    test = resolve(holder, set())
    return (method.startswith('test_') and test is not None
            and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == operation for node in python_source.walk(test)))
