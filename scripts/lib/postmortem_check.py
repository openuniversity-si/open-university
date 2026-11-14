"""Blameless postmortems name the check that prevents their class (D-069 item 9; docs/process/postmortems/TEMPLATE.md).

Every postmortem in process.postmortem_dir carries a section under process.postmortem_check_heading with one
`- check: <file>` line per gate check file and one `- test: <file>::<name>` line per test that proves it. The check
refuses a postmortem that names none, or whose files or tests do not exist: an incident ends with a check that runs,
not with a sentence. A Python test is `def <name>(`; any other test file must spell the name.

check(root) is the structure-check half (the `structure check` stage).
"""
from pathlib import Path
import re

import config


def setting(name):
    return config.get(f'process.{name}')


def section(text, heading):
    """The body of a level-two heading, up to the next level-two heading or the end; None when absent."""
    found = re.search(rf'^## {re.escape(heading)}[ \t]*$\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return found.group(1) if found else None


def references(body):
    """(check files, test refs) named under the heading, in order."""
    check_label, test_label = setting('postmortem_ref_check'), setting('postmortem_ref_test')
    found = {check_label: [], test_label: []}
    for label, value in re.findall(rf'^- ({re.escape(check_label)}|{re.escape(test_label)}): (\S+)[ \t]*$', body, re.M):
        found[label].append(value)
    return found[check_label], found[test_label]


def test_exists(path, name):
    if not path.is_file():
        return False
    text = path.read_text(encoding='utf-8', errors='replace')
    if path.suffix == '.py':
        return re.search(rf'\bdef {re.escape(name)}\(', text) is not None
    return re.search(rf'\b{re.escape(name)}\b', text) is not None


def errors_for(path, root):
    name = path.relative_to(root).as_posix()
    body = section(path.read_text(encoding='utf-8'), setting('postmortem_check_heading'))
    if body is None:
        return [f'{name}: no "## {setting("postmortem_check_heading")}" section; name the check that prevents the class '
                '(D-069 item 9)']
    checks, tests = references(body)
    check_label, test_label = setting('postmortem_ref_check'), setting('postmortem_ref_test')
    errors = []
    if not checks:
        errors.append(f'{name}: the preventing-check section names no check ("- {check_label}: <file>")')
    if not tests:
        errors.append(f'{name}: the preventing-check section names no test ("- {test_label}: <file>::<name>")')
    for ref in checks:
        if not (root / ref).is_file():
            errors.append(f'{name}: check {ref} does not exist')
    for ref in tests:
        file, _, test = ref.partition('::')
        if not test:
            errors.append(f'{name}: test {ref} names no test (write <file>::<name>)')
        elif not test_exists(root / file, test):
            errors.append(f'{name}: test {ref} does not exist')
    return errors


def check(root):
    """Errors of every postmortem under process.postmortem_dir (the template excluded). Empty when there is none."""
    root = Path(root)
    directory = root / setting('postmortem_dir')
    if not directory.is_dir():
        return []
    errors = []
    for path in sorted(directory.glob('*.md')):
        if path.name == setting('postmortem_template'):
            continue
        if not re.match(setting('postmortem_name_pattern'), path.name):
            errors.append(f'{path.relative_to(root).as_posix()}: the name must match '
                          f'{setting("postmortem_name_pattern")} (YYYY-MM-DD-slug.md)')
        errors += errors_for(path, root)
    return errors
