"""A git merge driver for committed generated files (CENSO-NO-MANIFESTO 3bis; D-069 items 1 and 2, TX32).

The registry aggregates and the generated modules stay committed (CODEOWNERS was one until VAZÃO F17, the deleted
product's tsconfig paths file another until OU-DECOUPLE F5, D-113); twelve open pull requests once edited one of them on
the same day. A generated file is a pure
function of its sources, so a conflict in it is never a person's to resolve: .gitattributes names this driver for each
such file (`<path> merge=<generate.merge_driver_name>`), and the driver writes the regeneration from the merged sources.

git merges in memory and calls a driver once per path before it writes the worktree, so the merged sources are not on
disk yet. The driver rebuilds them: the other side is the one GITHEAD_<sha> variable git merge and git pull set; the
merged tree is `git merge-tree --write-tree HEAD <theirs>` (the nested call of this driver, told by
generate.merge_inner_env, does a plain 3-way merge); it checks that tree out as a throwaway detached worktree and runs
scripts/generate on it, pinned to the file store, then takes the target's output. When the target's sources conflict, or no single other
head is known (a rebase, a cherry-pick), it falls back to `git merge-file`, so a real conflict stays one. The generated
drift stage still refuses a stale file whatever happened here.

A path that is no generate target (.gitattributes names units/*/unit.json and the registry key files) merges 3-way, and
a .json one whose textual merge conflicts merges structurally (merge_json): objects per key, string lists as sets, so
two lanes appending different `requires` or `x-readers` entries after the same last line no longer conflict.

  scripts/merge-regenerate %O %A %B %P     the driver (git calls it; exit 0 merged, 1 conflict)
  scripts/merge-regenerate install [--root DIR]
                                           register the driver in the checkout's git config (scripts/cloud/setup.sh)
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import config
import generate
import units

ROOT = Path(__file__).resolve().parent.parent.parent
HEAD_VARIABLE = 'GITHEAD_'
DRIVER = 'scripts/merge-regenerate %O %A %B %P'


def wiring(name, root=None):
    """A generate.merge_* registry value as declared: the driver's wiring is static (.gitattributes spells the name), so
    it never costs a read of the change store, and a merge works offline."""
    return config.entry(f'generate.{name}', root)['default']


def _git(root, *args, env=None, text=True):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=text, env=env)


def target_of(root, path):
    """(name, target) of the committed generate target whose output is this one file, else (None, None)."""
    for target in config.get('generate.targets', root):
        if target['committed'] and target['enabled'] and target['output'] == path:
            return target['name'], target
    return None, None


def their_head(environ=None):
    """The other head of a git merge, from its one GITHEAD_<sha> variable; None when there is not exactly one."""
    heads = [name[len(HEAD_VARIABLE):] for name in (os.environ if environ is None else environ) if name.startswith(HEAD_VARIABLE)]
    return heads[0] if len(heads) == 1 else None


def merged_tree(root, theirs):
    """(tree id, conflicted paths) of HEAD merged with theirs, computed in the object store."""
    env = {**os.environ, wiring('merge_inner_env', root): '1'}
    done = _git(root, 'merge-tree', '--write-tree', '--name-only', 'HEAD', theirs, env=env)
    lines = done.stdout.splitlines()
    if not lines or done.returncode not in (0, 1):
        return None, []
    conflicted = []
    for line in lines[1:]:
        if not line:
            break
        conflicted.append(line)
    return lines[0], conflicted


def merge_file(ours, base, theirs):
    """git merge-file in place on ours: 0 when clean, else the conflict count (git keeps the markers)."""
    return subprocess.run(['git', 'merge-file', '-q', ours, base, theirs]).returncode


class Clash(ValueError):
    """Both sides changed the same JSON value differently: a real conflict."""


_MISSING = object()  # a key one side does not have; no JSON value equals it


def _merge_value(base, ours, theirs):
    """The 3-way merge of one JSON value. An object merges per key; a list of distinct strings (an `x-readers` list)
    merges as a set; either keeps sorted order when ours had it. Anything else changed on both sides clashes."""
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    if all(isinstance(side, dict) for side in (base, ours, theirs)):
        merged = {}
        for key in [*ours, *(key for key in theirs if key not in ours)]:
            value = _merge_value(base.get(key, _MISSING), ours.get(key, _MISSING), theirs.get(key, _MISSING))
            if value is not _MISSING:
                merged[key] = value
        return dict(sorted(merged.items())) if list(ours) == sorted(ours) else merged
    if all(isinstance(side, list) and all(isinstance(item, str) for item in side) and len(set(side)) == len(side)
           for side in (base, ours, theirs)):
        dropped = set(base) - set(theirs)
        merged = [item for item in ours if item not in dropped]
        merged += [item for item in theirs if item not in base and item not in ours]
        return sorted(merged) if ours == sorted(ours) else merged
    raise Clash()


def _json_style(text):
    """The json.dumps arguments that write this text back byte for byte, or None (the merge then leaves the file alone)."""
    document = json.loads(text)
    lines = text.splitlines()
    indent = len(lines[1]) - len(lines[1].lstrip(' ')) if lines[1:] else None  # the file's own indent
    for ascii_only in (False, True):
        if json.dumps(document, indent=indent, ensure_ascii=ascii_only) + '\n' == text:
            return {'indent': indent, 'ensure_ascii': ascii_only}
    return None


def merge_json(ours, base, theirs):
    """The structural merge of a hand-written JSON file (a unit's `requires`, a registry key's `x-readers`): two
    branches that each append an entry after the same last line are a textual conflict for git (both rewrite that line
    to add its comma), not a conflict of the document. Writes the merge into ours and returns 0; returns 1 and leaves
    ours alone when a side is not JSON, ours is in a style json.dumps does not write back exactly, or a value clashes."""
    try:
        texts = [Path(side).read_text(encoding='utf-8') for side in (base, ours, theirs)]
        style = _json_style(texts[1])
        if style is None:
            return 1
        merged = _merge_value(*(json.loads(text) for text in texts))
    except ValueError:  # json.JSONDecodeError, UnicodeDecodeError and Clash
        return 1
    Path(ours).write_text(json.dumps(merged, **style) + '\n', encoding='utf-8')
    return 0


def merge_source(ours, base, theirs, path):
    """A path that is no generate target: the plain 3-way merge; when that conflicts on a .json file, the structural
    merge, and git's conflict markers only if that fails too."""
    kept = Path(ours).read_bytes()
    conflicts = merge_file(ours, base, theirs)
    if not conflicts or not path.endswith('.json'):
        return conflicts
    marked = Path(ours).read_bytes()
    Path(ours).write_bytes(kept)
    if merge_json(ours, base, theirs) == 0:
        return 0
    Path(ours).write_bytes(marked)
    return conflicts


def regenerate(root, name, path, tree):
    """The target's file rendered from a tree, or None if the generator refuses it. The tree is checked out as a
    detached worktree of a throwaway commit, so a renderer that lists tracked files sees exactly the merged tree."""
    commit = _git(root, 'commit-tree', tree, '-m', 'merge-regenerate: the merged sources')
    if commit.returncode:
        return None
    with tempfile.TemporaryDirectory() as folder:
        merged, out = Path(folder) / 'tree', Path(folder) / 'out'
        added = _git(root, 'worktree', 'add', '--detach', '--quiet', str(merged), commit.stdout.strip())
        if added.returncode:
            return None
        try:
            env = {**os.environ, 'OU_CONFIG_STORE': 'file'}
            env.pop(wiring('merge_inner_env', root), None)
            done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/generate.py'), name, '--root', str(merged),
                                   '--out', str(out)], capture_output=True, text=True, env=env)
        finally:
            _git(root, 'worktree', 'remove', '--force', str(merged))
        produced = out / path
        if done.returncode or not produced.is_file():
            return None
        return produced.read_text(encoding='utf-8')


def inner(root, name, base, ours, theirs):
    """The nested merge, inside the merge-tree that rebuilds the merged sources. A renderer that keeps hand-written
    content from its own output declares strip(root, text): only that part is merged 3-way, and a conflict in it is a
    real one. A renderer without it is a pure function of its sources, so ours stands in and the outer call
    regenerates the whole file."""
    renderer = generate.renderer(name)
    if not hasattr(renderer, 'strip'):
        kept = Path(ours).read_bytes()
        if merge_file(ours, base, theirs):
            Path(ours).write_bytes(kept)
        return 0
    try:
        for side in (base, ours, theirs):
            Path(side).write_text(renderer.strip(root, Path(side).read_text(encoding='utf-8')), encoding='utf-8')
    except ValueError:
        return merge_file(ours, base, theirs)
    return merge_file(ours, base, theirs)


def drive(root, base, ours, theirs, path, environ=None):
    """The driver: write the merge of path into ours; 0 when it merged, non-zero for a conflict."""
    environ = os.environ if environ is None else environ
    name, target = target_of(root, path)
    if name is None:
        return merge_source(ours, base, theirs, path)
    if wiring('merge_inner_env', root) in environ:
        return inner(root, name, base, ours, theirs)
    other = their_head(environ)
    tree, conflicted = merged_tree(root, other) if other else (None, [])
    if tree is None or any(units.match(glob, item) for glob in target['sources'] for item in conflicted):
        return merge_file(ours, base, theirs)
    text = regenerate(root, name, path, tree)
    if text is None:
        return merge_file(ours, base, theirs)
    Path(ours).write_text(text, encoding='utf-8')
    return 0


def install(root):
    """Register the driver in the checkout's git config (idempotent)."""
    name = wiring('merge_driver_name', root)
    _git(root, 'config', f'merge.{name}.name', 'regenerate a generated file from the merged sources (scripts/generate)')
    _git(root, 'config', f'merge.{name}.driver', DRIVER)
    return name


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    config.pin_store('file')  # a merge result depends on the trees alone, never on the shared change store
    if argv[:1] == ['install']:
        root = Path(argv[argv.index('--root') + 1]) if '--root' in argv else ROOT
        print(f'merge-regenerate: merge.{install(root)}.driver registered')
        return 0
    if len(argv) != len(['base', 'ours', 'theirs', 'path']):
        print('usage: scripts/merge-regenerate %O %A %B %P | install [--root DIR]', file=sys.stderr)
        return 1
    root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip() or Path.cwd())
    base, ours, theirs, path = argv
    return drive(root, base, ours, theirs, path)


if __name__ == '__main__':
    sys.exit(main())
