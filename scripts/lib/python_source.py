"""Read-only Python syntax shared by tree checks for one run (D-291).

Keys are the complete source text, never a filename or a stale stat. The snapshot is discarded on exit; consumers
must not mutate its nodes. Outside a snapshot the same functions have standard-library semantics.
"""
import ast
import heapq
import multiprocessing
from contextlib import contextmanager
from contextvars import ContextVar

_active = ContextVar('python_source_snapshot', default=None)


@contextmanager
def snapshot():
    if _active.get() is not None:
        yield
        return
    token = _active.set(({}, {}, {}))
    try:
        yield
    finally:
        _active.reset(token)


def parse(text):
    held = _active.get()
    if held is None:
        return ast.parse(text)
    trees, _, _ = held
    if text not in trees:
        trees[text] = ast.parse(text)
    return trees[text]


def walk(tree):
    held = _active.get()
    if held is None:
        return ast.walk(tree)
    _, nodes, _ = held
    if tree not in nodes:
        nodes[tree] = tuple(ast.walk(tree))
    return iter(nodes[tree])


def select(tree, *kinds):
    """The standard breadth-first walk restricted to node types, indexed once for all checks."""
    held = _active.get()
    if held is None:
        return (node for node in ast.walk(tree) if isinstance(node, kinds))
    _, _, indexes = held
    if tree not in indexes:
        by_type = {}
        for position, node in enumerate(walk(tree)):
            by_type.setdefault(type(node), []).append((position, node))
        indexes[tree] = by_type
    if ast.AST in kinds:
        return walk(tree)  # already in breadth-first order; do not merge every typed index back together
    lists = [nodes for kind, nodes in indexes[tree].items() if issubclass(kind, kinds)]
    return (node for _, node in heapq.merge(*lists))


def _invoke(task):
    function, args = task
    return function(*args)


def checks(tasks, paths, workers, minimum):
    """Run independent read-only checks over shared syntax; small fixture trees use the identical inline calls."""
    paths = list(paths)
    if workers <= 1 or len(paths) < minimum:
        return [_invoke(task) for task in tasks]
    # Parse before fork: children inherit the immutable syntax pages rather than parsing the same source again.
    for path in paths:
        try:
            tree = parse(path.read_text(encoding='utf-8'))
            tuple(select(tree, ast.AST))
        except (OSError, SyntaxError, UnicodeError):
            pass  # each owning check retains its existing invalid-source/error policy
    with multiprocessing.get_context('fork').Pool(processes=workers) as pool:
        return pool.map(_invoke, tasks)
