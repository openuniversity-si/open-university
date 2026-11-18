"""The checks the merge queue requires (CHK, the Configuration system, PADRAO-DEV F7d, D-320): every job of a GitHub
workflow is one check, named by its `name:`, and its state is derived from the files, never written.

  staged     the job is in a workflow of services/runner/github/ only: a session may write it there, and only the owner
             installs it as .github/workflows/ (D-087)
  installed  the job is in a workflow of .github/workflows/, and no ruleset requires it
  required   a ruleset of .github/rulesets/ lists its name among its required status checks

Only a job of a workflow that runs on `pull_request` is a check: a check judges a pull request. A workflow that runs
only on push to main (the full suite, the deploy doorbell) or only acts in the merge queue (the doorbell's prepare
ring) does work after or around the judgement, so the queue must never wait for it (requiring the doorbell would block
every merge on the deploy service).

`check` refuses a required check that no installed job produces (the queue would wait for it forever) and an installed
workflow that differs from its staged copy (the copy the owner installs is the one a session reviewed).
"""
import json
from pathlib import Path
import re

STAGED = 'services/runner/github'
INSTALLED = '.github/workflows'
RULESETS = '.github/rulesets'

JOB = re.compile(r'^  ([A-Za-z0-9_-]+):\s*$')
NAME = re.compile(r'^    name:\s*(.+?)\s*$')


TRIGGER = re.compile(r'^  ([a-z_]+):')


def triggers(text):
    """The events a workflow runs on: the keys under its top-level `on:` (a list or a scalar `on:` is read too)."""
    found, inside = set(), False
    for line in text.splitlines():
        if line.startswith('on:'):
            rest = line[3:].strip()
            if rest:
                return set(re.findall(r'[a-z_]+', rest))
            inside = True
            continue
        if inside and line and not line.startswith(' ') and not line.startswith('#'):
            break
        matched = TRIGGER.match(line) if inside else None
        if matched:
            found.add(matched.group(1))
    return found


def judges_pull_requests(text):
    return 'pull_request' in triggers(text)


def job_names(text):
    """The check names of a workflow: each job's `name:` under `jobs:`, else the job id; a name built from an
    expression (a matrix) is a family of checks, not one, and is left out."""
    names, inside, job = [], False, None
    for line in text.splitlines():
        if line.startswith('jobs:'):
            inside = True
            continue
        if inside and line and not line.startswith(' ') and not line.startswith('#'):
            inside = False
        if not inside:
            continue
        matched = JOB.match(line)
        if matched:
            if job is not None:
                names.append(job)
            job = matched.group(1)
            continue
        named = NAME.match(line)
        if named and job is not None:
            job = named.group(1).strip('"\'')
            names.append(job)
            job = None
    if job is not None:
        names.append(job)
    return [name for name in names if '${{' not in name]


def required(root):
    """{check name: ruleset file} of every required status check of the rulesets."""
    found = {}
    for path in sorted((Path(root) / RULESETS).glob('*.json')):
        body = json.loads(path.read_text())
        for rule in body.get('rules', []):
            if rule.get('type') == 'required_status_checks':
                for item in rule.get('parameters', {}).get('required_status_checks', []):
                    found[item['context']] = path.relative_to(root).as_posix()
    return found


def workflows(root, folder):
    return {path.name: path for path in sorted((Path(root) / folder).glob('*.yml'))}


def checks(root):
    """[{name, state, workflow, staged, installed, required_by}] of every check the tree names."""
    root = Path(root)
    staged, installed, wanted = workflows(root, STAGED), workflows(root, INSTALLED), required(root)
    found = {}
    for kind, files in (('staged', staged), ('installed', installed)):
        for name, path in files.items():
            text = path.read_text()
            if not judges_pull_requests(text):
                continue
            for check in job_names(text):
                entry = found.setdefault(check, {'name': check, 'workflow': name, 'staged': False, 'installed': False})
                entry[kind] = True
    for check, ruleset in wanted.items():
        found.setdefault(check, {'name': check, 'workflow': None, 'staged': False, 'installed': False})
    for entry in found.values():
        entry['required_by'] = wanted.get(entry['name'])
        entry['state'] = 'required' if entry['required_by'] else 'installed' if entry['installed'] else 'staged'
    return sorted(found.values(), key=lambda entry: entry['name'])


def check(root):
    """The refusals: a required check no installed job produces, an installed workflow that differs from its staged copy."""
    root = Path(root)
    errors = [f'check {entry["name"]}: required by {entry["required_by"]} but no installed workflow runs it'
              for entry in checks(root) if entry['required_by'] and not entry['installed']]
    staged = workflows(root, STAGED)
    for name, path in workflows(root, INSTALLED).items():
        if name in staged and staged[name].read_bytes() != path.read_bytes():
            errors.append(f'{INSTALLED}/{name}: differs from its staged copy {STAGED}/{name}; the owner installs the staged copy')
    return errors


def check_id(name):
    return 'CHK-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
