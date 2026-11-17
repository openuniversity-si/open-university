"""Retired vendors (D-318), a module of scripts/structure-check and the body of scripts/retired-vendors.

Nothing of ours relates to a vendor we retired (D-318): no code, configuration, dependency, workflow, environment
variable, CSP entry, operating instruction or deploy path. check(root) returns the errors of:
  path      a tracked path that matches a pattern of structure.retired_vendor_terms;
  mention   a line of a tracked text file that matches one;
each outside structure.record_globs, the historical records that describe the past and are not rewritten (the same
records retired_products keeps, D-113), which hold the patterns' own definition too. The patterns are registry entries
(config/registry/structure/), case-insensitive and Perl-compatible; one `git grep -P` finds the mentions.

    scripts/retired-vendors [--root DIR] [--no-records] [--records]

prints every reference (path:line: text) and a summary line, and exits 1 when there is one. --root judges another
checkout (the site's repository, which has no records: pass --no-records there); --records prints each record glob with
the number of tracked files it keeps, the justified exceptions of the proof.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

import config
from gate_areas import glob_match

SHOWN = 160  # characters of a matched line an error quotes


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True)


def tracked(root):
    listed = _git(root, 'ls-files', '-z')
    if listed.returncode != 0:
        raise RuntimeError(f'{root}: not a git checkout ({listed.stderr.decode().strip()})')
    return [path for path in listed.stdout.decode().split('\0') if path]


def kept(path, records):
    return any(glob_match(path, pattern) for pattern in records)


def references(root, terms, records):
    """[(path, line or None, text)]: every tracked path and every line of a tracked text file outside records that
    matches a term; line None marks the path itself."""
    root = Path(root)
    if not terms:
        return []
    names = re.compile('|'.join(f'(?:{term})' for term in terms), re.IGNORECASE)
    found = [(path, None, path) for path in tracked(root) if names.search(path) and not kept(path, records)]
    args = ['grep', '-P', '-i', '-I', '-n', '-z', '--full-name']
    for term in terms:
        args += ['-e', term]
    done = _git(root, *args, '--', '.')
    if done.returncode not in (0, 1):
        raise RuntimeError(f'git grep: {done.stderr.decode().strip()}')
    for record in done.stdout.decode(errors='replace').split('\n'):
        parts = record.split('\0', 2)
        if len(parts) == 3 and not kept(parts[0], records):
            found.append((parts[0], int(parts[1]), parts[2].strip()[:SHOWN]))
    return sorted(found, key=lambda item: (item[0], item[1] or 0))


def check(root):
    """The structure check's errors: one per reference outside the records. A directory that is not a git checkout
    (a fixture tree of the structure tests) has no tracked file to judge, as in retired_products."""
    errors = []
    try:
        found = references(root, config.get('structure.retired_vendor_terms'), config.get('structure.record_globs'))
    except RuntimeError:
        return []
    for path, line, text in found:
        where = path if line is None else f'{path}:{line}'
        what = 'its path names' if line is None else f'"{text}" names'
        errors.append(f'{where}: {what} a retired vendor (structure.retired_vendor_terms); nothing of ours relates to '
                      'one, and only the records of structure.record_globs keep the past (D-318)')
    return errors


def record_counts(root, records):
    paths = tracked(root)
    return [(pattern, sum(1 for path in paths if glob_match(path, pattern))) for pattern in records]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/retired-vendors', description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--no-records', action='store_true', help='judge every tracked file (a checkout with no records)')
    parser.add_argument('--records', action='store_true', help='print the record globs and the files each keeps')
    args = parser.parse_args(argv)
    terms = config.get('structure.retired_vendor_terms')
    records = [] if args.no_records else config.get('structure.record_globs')
    if args.records:
        for pattern, count in record_counts(args.root, records):
            print(f'record {pattern}: {count} tracked file(s)')
    found = references(args.root, terms, records)
    for path, line, text in found:
        print(path if line is None else f'{path}:{line}: {text}')
    files = len({path for path, _, _ in found})
    print(f'retired-vendors: {len(found)} reference(s) in {files} file(s) of {args.root} outside '
          f'{len(records)} record glob(s); patterns {", ".join(terms)}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
