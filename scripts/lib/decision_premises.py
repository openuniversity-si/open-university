"""A decision that a PR adds or changes cites its premises (D-066, D-069 item 10; docs/domain/DECISIONS.md).

A row of the decision register carries a `Premises:` clause in its text, the same form as a PR body's line: the
premise ids it rests on, or `none`. The clause is validated with premises.check_line, so an unknown, refused or
unsettled high-radius premise is refused here exactly as it is in a PR body (one validation, no second parser).

Only rows the change adds or edits are judged: a row identical to the base's is an existing decision, and existing
decisions are not retro-judged. Without a base there is no change to diff, so nothing is judged.

check(root, base, changed) is the structure-check half: (errors, warnings).
"""
from pathlib import Path
import re
import subprocess

import config
import premises

ROW = re.compile(r'^\|\s*D-\d{3}\s*\|')


_SETTINGS = {}


def setting(name):
    if name not in _SETTINGS:  # read once per process: config.get replays the store on every call
        _SETTINGS[name] = config.get(f'process.{name}')
    return _SETTINGS[name]


def clause(row):
    """The premise tokens of a row's `Premises:` clause, None when the row has no clause."""
    found = re.search(rf'{re.escape(premises.setting("line_name"))}:[ \t]*([^|]*?)[ \t]*(?=\||$)', row)
    return found.group(1) if found else None


def base_rows(root, base):
    """The register's rows on the base ref, or None when the base cannot be read."""
    shown = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{setting("decisions_register")}'],
                           capture_output=True, text=True)
    if shown.returncode != 0:
        return None
    return {line for line in shown.stdout.splitlines() if ROW.match(line)}


def check(root, base, changed=(), by_id=None):
    """(errors, warnings) of the rows the change adds or edits (D-066: cite the premise; D-069 item 10)."""
    root = Path(root)
    register = root / setting('decisions_register')
    if base is None:
        return [], []
    existing = base_rows(root, base)
    if existing is None:
        return [], [f'{setting("decisions_register")}: base {base} cannot be read; decision premises are not judged']
    if by_id is None:
        by_id, _ = premises.load(root)
    errors, warnings = [], []
    if not register.is_file():
        return errors, warnings
    for line in register.read_text(encoding='utf-8').splitlines():
        if not ROW.match(line) or line in existing:
            continue
        ident = line.split('|')[1].strip()
        tokens = clause(line)
        if tokens is None:
            errors.append(f'DECISIONS.md {ident}: an added or changed decision cites its premises '
                          f'("{premises.setting("line_name")}: P-NN, ..." or "{premises.setting("line_name")}: '
                          f'{premises.setting("none_token")}"; D-066)')
            continue
        row_errors, row_warnings, _ = premises.check_line(f'{premises.setting("line_name")}: {tokens}', by_id, changed)
        errors += [f'DECISIONS.md {ident}: {problem}' for problem in row_errors]
        warnings += [f'DECISIONS.md {ident}: {problem}' for problem in row_warnings]
    return errors, warnings
