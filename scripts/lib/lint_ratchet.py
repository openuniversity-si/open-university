"""The Python lint ratchet (PADRAO-DEV F4b, docs/programs/padrao-dev/phases/F4.md): no file of the engine gains a lint
finding, with no baseline file to keep.

ruff (pinned in the toolchain, toolchain.ruff_version) runs over the engine's tracked Python in the rule families of
rules.lint_select, leaving out the rules of rules.lint_ignored, which still have a legacy. Any finding fails. The
ignored list only shrinks: it holds at most rules.lint_ignored_max rules (a budget that only tightens), and a rule
with no finding left must leave it, so cleaning a legacy closes its door behind it.

  scripts/lint-ratchet           the findings (exit 1 when any) and the ignored rules that no longer need to be
                                 ignored (exit 1 when any)
  scripts/lint-ratchet --json F  the same as data
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

CODE_ROOTS = ('scripts', 'infra', 'services')


def ruff_binary(root=ROOT):
    """The toolchain's ruff, else one on PATH; None when there is neither."""
    pinned = Path(os.environ.get('OU_TOOLCHAIN_DIR') or Path(root) / '.toolchain') / 'bin' / 'ruff'
    return str(pinned) if pinned.is_file() else shutil.which('ruff')


def python_files(root=ROOT):
    listed = subprocess.run(['git', 'ls-files', '-z', '--', *(f'{folder}/*.py' for folder in CODE_ROOTS)],
                            cwd=root, capture_output=True, check=True).stdout
    return sorted(name for name in listed.decode().split('\0') if name)


def findings(root=ROOT, select=None, ignored=None, run=subprocess.run, binary=None, files=None):
    """[{rule, file, line, message}] of ruff over the engine's Python, with `select` minus `ignored`."""
    select = select if select is not None else config.get('rules.lint_select')
    ignored = ignored if ignored is not None else config.get('rules.lint_ignored')
    binary = binary or ruff_binary(root)
    if binary is None:
        raise RuntimeError('lint ratchet: no ruff (bash scripts/cloud/setup.sh installs the pinned one)')
    files = files if files is not None else python_files(root)
    if not files:
        return []
    command = [binary, 'check', '--isolated', '--no-cache', '--output-format', 'json', '--exit-zero',
               '--select', ','.join(select), *(['--ignore', ','.join(ignored)] if ignored else []), *files]
    answer = run(command, cwd=root, capture_output=True, text=True, check=False)
    if answer.returncode != 0:
        raise RuntimeError(f'lint ratchet: ruff failed: {answer.stderr.strip()[-300:]}')
    return [{'rule': item['code'], 'file': Path(item['filename']).resolve().relative_to(Path(root).resolve()).as_posix(),
             'line': item['location']['row'], 'message': item['message']} for item in json.loads(answer.stdout or '[]')]


def stale(root=ROOT, ignored=None, select=None, run=subprocess.run, binary=None, files=None):
    """The ignored rules with no finding left: they must leave rules.lint_ignored."""
    ignored = ignored if ignored is not None else config.get('rules.lint_ignored')
    still = {item['rule'] for item in findings(root, select=list(ignored), ignored=[], run=run, binary=binary, files=files)}
    return sorted(rule for rule in ignored if rule not in still)


def judge(root=ROOT, run=subprocess.run, binary=None, files=None):
    ignored = config.get('rules.lint_ignored')
    found = findings(root, ignored=ignored, run=run, binary=binary, files=files)
    leaving = stale(root, ignored=ignored, run=run, binary=binary, files=files)
    over = len(ignored) - config.get('rules.lint_ignored_max')
    return {'findings': found, 'stale_ignored': leaving, 'ignored_over_max': max(over, 0)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/lint-ratchet', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json')
    args = parser.parse_args(argv)
    result = judge()
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + '\n')
    for item in result['findings']:
        print(f'{item["file"]}:{item["line"]}: {item["rule"]} {item["message"]}')
    for rule in result['stale_ignored']:
        print(f'{rule}: no finding left; remove it from rules.lint_ignored')
    if result['ignored_over_max']:
        print(f'rules.lint_ignored holds {result["ignored_over_max"]} rule(s) more than rules.lint_ignored_max')
    print(f'lint ratchet: {len(result["findings"])} finding(s), {len(result["stale_ignored"])} stale ignored rule(s)')
    return 1 if result['findings'] or result['stale_ignored'] or result['ignored_over_max'] else 0


if __name__ == '__main__':
    sys.exit(main())
