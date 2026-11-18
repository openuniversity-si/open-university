"""One generator for every derived file (D-069 items 1 and 2, plan v3.1 G1): `scripts/generate <target>|all`.

The targets are data: the registry parameter generate.targets (config/registry/generate.json) gives each one its
sources, its output, whether the output is committed and whether the target is enabled, and the parameter's own
JSON Schema validates them. The renderer of target <name> is scripts/lib/generate_<name>.py; its render(root, target)
returns {path: text}. A committed target owns its output directory: a file there that its sources no longer produce is
drift too, unless the target says `owns_output: false` (D-095: the registry aggregates share config/registry/ with
the files that are not split). --check compares every enabled committed target with its regeneration and exits 1 on drift; it is the
`generated drift` gate stage. A target that is not committed (docs) prints on demand or writes under --out.
A disabled target is listed and skipped; `requires` names the glob that must match before it may be enabled.
"""
import argparse
import importlib
from pathlib import Path
import re
import subprocess
import sys

import config
from globs import glob_match

ROOT = Path(__file__).resolve().parents[2]


class GenerateError(ValueError):
    pass


def default_root():
    found = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return Path(found.stdout.strip()) if found.returncode == 0 else ROOT


def targets(root=None):
    """{name: target} in registry order (config.get validates any stored override); a name is declared once."""
    found = {}
    for target in config.get('generate.targets', root):
        if target['name'] in found:
            raise GenerateError(f'generate.targets declares {target["name"]} twice')
        found[target['name']] = target
    return found


def module_name(source):
    """The generated module of one source path: contracts/events/pr.opened.v1.json -> contracts_events_pr_opened_v1."""
    return re.sub(r'[^a-z0-9]+', '_', Path(source).with_suffix('').as_posix().lower()).strip('_')


def class_name(text):
    return ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^A-Za-z0-9]+', text) if part)


def sources(root, target):
    """The repository paths a target reads, sorted, from its source globs."""
    found = set()
    for pattern in target['sources']:
        found |= {path.relative_to(root).as_posix() for path in Path(root).glob(pattern) if path.is_file()}
    return sorted(found)


def changed_paths(root, base):
    """The paths this checkout changes against `base`, as `scripts/test-suite --changed` reads them (VAZÃO F50): the
    gate's diff `base...HEAD` (git_objects.changed_paths) plus what is not committed yet (staged, unstaged, untracked).
    `--changed` used to read its paths from stdin only, so typed by hand it waited on stdin for good: a lane's
    `scripts/generate --changed` hung for more than 10 minutes on 03/11 while `scripts/generate registry` took seconds."""
    import git_objects  # the gate's own diff (D-322: layer 0, so generate imports nothing of the gate)
    git = ['git', '-C', str(root)]
    try:
        committed = git_objects.changed_paths(root, base, 'HEAD')
        pending = subprocess.run(git + ['diff', '--no-renames', '--name-only', '-z', 'HEAD'], capture_output=True,
                                 check=True).stdout.decode().split('\0')
        untracked = subprocess.run(git + ['ls-files', '--others', '--exclude-standard', '-z'], capture_output=True,
                                   check=True).stdout.decode().split('\0')
    except subprocess.CalledProcessError as error:
        raise GenerateError(f'--changed: cannot diff against {base} (git exited {error.returncode}); '
                            'fetch it, or pass --base REF') from error
    return sorted({path for path in committed + pending + untracked if path})


def affected(paths, root=None):
    """The committed, enabled targets whose source globs name one of the changed paths, in registry order (D-222 (5)).

    A non-committed target (docs, status, census) is printed on demand and never written by a commit, so it is left out.
    """
    root = Path(root or default_root())
    changed = [path for path in paths if path]
    return [
        name
        for name, target in targets(root).items()
        if target['committed'] and skip_reason(root, target) is None
        and any(glob_match(path, pattern) for path in changed for pattern in target['sources'])
    ]


def renderer(name):
    try:
        return importlib.import_module('generate_' + name.replace('-', '_'))
    except ModuleNotFoundError as error:
        raise GenerateError(f'{name}: no renderer scripts/lib/generate_{name.replace("-", "_")}.py') from error


def skip_reason(root, target):
    """Why a target cannot run now, else None."""
    if not target['enabled']:
        until = f' until {target["requires"]} exists' if 'requires' in target else ''
        slot = f' ({target["slot"]})' if 'slot' in target else ''
        return f'disabled{until}{slot}'
    if 'requires' in target and not any(Path(root).glob(target['requires'])):
        return f'enabled, but nothing matches {target["requires"]}'
    return None


def expected(root, name, target):
    return renderer(name).render(Path(root), target)


def drift(root=None, names=None):
    """Every committed file of an enabled committed target that differs from its regeneration, is missing, or has no
    source left. names limits the targets; None means all of them."""
    root = Path(root or ROOT)
    problems = []
    for name, target in targets(root).items():
        if names is not None and name not in names:
            continue
        if not target['committed'] or skip_reason(root, target):
            continue
        want = expected(root, name, target)
        for path, text in want.items():
            file = root / path
            if not file.is_file():
                problems.append(f'{path}: missing; run scripts/generate {name}')
            elif file.read_text(encoding='utf-8') != text:
                problems.append(f'{path}: differs from its regeneration; run scripts/generate {name}')
        folder = root / target['output']
        if folder.is_dir() and target.get('owns_output', True):
            for file in sorted(item for item in folder.iterdir() if item.is_file()):
                path = file.relative_to(root).as_posix()
                if path not in want:
                    problems.append(f'{path}: no source produces it; scripts/generate {name} deletes it')
    return problems


def write(root, name, target, out=None):
    """Write one target: a committed target into its output (removing orphans), any target under out when given."""
    root = Path(root)
    want = expected(root, name, target)
    if out is None and target.get('owns_output', True):
        folder = root / target['output']
        if folder.is_dir():
            for file in folder.iterdir():
                if file.is_file() and file.relative_to(root).as_posix() not in want:
                    file.unlink()
    base = root if out is None else Path(out)
    for path, text in want.items():
        file = base / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
    return sorted(base / path for path in want)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/generate', description=__doc__.splitlines()[0])
    parser.add_argument('target', nargs='?', default='all', help='a target name, or all (the default)')
    parser.add_argument('--check', action='store_true', help='exit 1 when a committed derived file drifts')
    parser.add_argument('--list', action='store_true', help='list the targets and their state')
    parser.add_argument('--stdout', action='store_true', help='print the one file of a single target, raw (how a reader consumes an on-demand aggregate)')
    parser.add_argument('--out', type=Path, help='write under this directory instead of in place')
    parser.add_argument('--root', type=Path, help='repository to generate in (default: the current checkout)')
    parser.add_argument('--changed', action='store_true', help="regenerate the committed targets this checkout's diff feeds (base...HEAD plus what is not committed, as scripts/test-suite --changed), print the files written (D-222 (5))")
    parser.add_argument('--base', help='with --changed: the base ref of the diff (default gate.changed_base_ref)')
    parser.add_argument('--stdin', action='store_true', help='with --changed: read the changed paths from stdin instead, one per line (the pre-commit stage, scripts/lib/generate_stage.sh)')
    args = parser.parse_args(argv)
    root = (args.root or default_root()).resolve()
    declared = targets(root)
    if (args.stdin or args.base) and not args.changed:
        parser.error('--stdin and --base go with --changed')
    if args.changed:
        if args.stdin:
            paths = [line.strip() for line in sys.stdin]
        else:
            paths = changed_paths(root, args.base or config.get('gate.changed_base_ref', root))
        names = affected(paths, root)
        base = root if args.out is None else Path(args.out)
        written = [path for name in names for path in write(root, name, declared[name], args.out)]
        for path in sorted(set(written)):
            print(Path(path).relative_to(base).as_posix())
        return 0
    if args.target != 'all' and args.target not in declared:
        parser.error(f'unknown target {args.target}; known: {", ".join(declared)}')
    chosen = list(declared) if args.target == 'all' else [args.target]
    if args.stdout:
        if len(chosen) != 1:
            parser.error('--stdout needs exactly one target')
        files = expected(root, chosen[0], declared[chosen[0]])
        if len(files) != 1:
            parser.error(f'--stdout needs a target with one file; {chosen[0]} has {len(files)}')
        sys.stdout.write(next(iter(files.values())))
        return 0
    if args.list:
        for name in chosen:
            target = declared[name]
            state = skip_reason(root, target) or 'enabled'
            print(f'{name}\t{"committed" if target["committed"] else "on demand"}\t{state}\t{target["description"]}')
        return 0
    if args.check:
        problems = drift(root, chosen)
        for line in problems:
            print('FAIL ' + line)
        for name in chosen:
            reason = skip_reason(root, declared[name])
            if reason:
                print(f'skip {name}: {reason}')
        return 1 if problems else 0
    for name in chosen:
        target = declared[name]
        reason = skip_reason(root, target)
        if reason:
            print(f'skip {name}: {reason}')
            continue
        if target['committed'] or args.out:
            for path in write(root, name, target, args.out):
                print(path.relative_to(root) if args.out is None else path)
        else:
            for path, text in expected(root, name, target).items():
                sys.stdout.write(f'<!-- {path} -->\n{text}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (GenerateError, config.ConfigError) as error:
        sys.exit(f'scripts/generate: {error}')
