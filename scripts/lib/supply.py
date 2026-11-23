"""Fornecimento, the 16th system of the engineering model (PADRAO-DEV F7c, D-320): the third-party components the
repository depends on, their suppliers and the advisories against them, read from the files that already pin them.

  DEP  a third-party component, derived, never written: a package of a pnpm lockfile (npm), a pinned requirement of a
       pip file (pypi), a tool of the engine's toolchain (scripts/cloud/toolchain.json), an action or an image a GitHub
       workflow or a Dockerfile uses. Its origin is pinned when the file fixes its content (an integrity or a checksum,
       a commit, a digest), not only a name that can move (a tag).
  SUP  a supplier, one file each under config/supply/suppliers/ (contracts/model/supplier.v1.json).
  ADV  an advisory against a DEP, from the audit snapshot config/supply/advisories.json (`scripts/supply audit`). It
       is affecting until the snapshot no longer has it, or exempted by config/supply/exemptions/<ADV id>.json with a
       reason and a deadline; past the deadline it is affecting again.

`scripts/supply audit` refreshes the snapshot (it runs `pnpm audit --json` for each lockfile, the only step that reaches
the network); `scripts/supply check` judges the tree with no network: the snapshot was taken on the lockfiles as they
are, and no advisory of a severity in supply.blocking_severities is affecting.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

SNAPSHOT = 'config/supply/advisories.json'
SUPPLIERS = 'config/supply/suppliers/SUP-*.json'
EXEMPTIONS = 'config/supply/exemptions'
TOOLCHAIN = 'scripts/cloud/toolchain.json'
WORKFLOWS = ('.github/workflows/*.yml', 'services/runner/github/*.yml')
DOCKERFILES = '**/Dockerfile'
PIP_FILES = 'infra/service/requirements*.txt'
LOCKFILES = '**/pnpm-lock.yaml'

PACKAGE = re.compile(r"^  '?((?:@[^@/\s]+/)?[^@\s']+)@([^(:'\s]+)[^:]*'?:\s*$")
INTEGRITY = re.compile(r'^\s+resolution: \{integrity: ')
USES = re.compile(r'^\s*(?:-\s+)?uses:\s*([^@\s]+)@(\S+)')
IMAGE = re.compile(r'^\s*image:\s*([^\s#]+)')
PIP = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;#]+)')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
FROM_LINE = re.compile(r'^\s*FROM\s+(?:--\S+\s+)*(?P<image>[^\s#]+)(?:\s+AS\s+(?P<alias>[A-Za-z0-9._-]+))?', re.IGNORECASE)
RUN_LINE = re.compile(r'^\s*RUN\s+(.+)', re.IGNORECASE)
CURL_PIPE_SH = re.compile(
    r'\b(?:curl|wget)\b[^;\n]*\|\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S+|env|sudo)\s+)*(?:/\S*/)?(?:ba|da|a|z|k)?sh\b'
)
NO_AUDIT = re.compile(r'(?:^|\s)--no-audit(?:\s|$)')


def setting(name, root=ROOT):
    return config.get(name, root)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tracked_or_glob(root, pattern):
    """Tracked paths matching `pattern` in a git work tree, else a plain glob (for non-git test fixtures)."""
    root = Path(root)
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', f':(glob){pattern}'], capture_output=True)
    if listed.returncode == 0:
        return sorted(name for name in listed.stdout.decode().split('\0') if name and 'node_modules' not in name)
    return sorted(path.relative_to(root).as_posix() for path in root.glob(pattern) if 'node_modules' not in path.parts)


def lockfiles(root):
    """The tree's lockfiles: the tracked ones in a git work tree, so an untracked copy (a session's worktree under
    .claude/worktrees/, a scratch checkout) is never audited nor compared; outside one (a test's fixture), the files."""
    return _tracked_or_glob(root, LOCKFILES)


def dockerfiles(root):
    """The tree's Dockerfiles (tracked in a git work tree, else globbed)."""
    return _tracked_or_glob(root, DOCKERFILES)


def pipfiles(root):
    """The tree's pinned pip requirements files (tracked in a git work tree, else globbed)."""
    return _tracked_or_glob(root, PIP_FILES)


def _dep(ecosystem, name, version, source, pinned):
    return {'ecosystem': ecosystem, 'name': name, 'version': version, 'source': source, 'pinned': pinned}


def lock_packages(text, source):
    """The packages of a pnpm lockfile (v9): its `packages:` section, one `name@version:` entry each, pinned when the
    entry carries its integrity."""
    found, current, inside = [], None, False
    for line in text.splitlines():
        if line == 'packages:':
            inside = True
            continue
        if inside and line and not line.startswith(' '):
            break
        if not inside:
            continue
        match = PACKAGE.match(line)
        if match:
            current = _dep('npm', match.group(1), match.group(2), source, False)
            found.append(current)
        elif current is not None and INTEGRITY.match(line):
            current['pinned'] = True
    return found


def workflow_parts(text, source):
    """The actions (`uses: owner/repo@ref`, pinned by a full commit) and the images (`image: name:tag`, pinned by a
    digest) of a GitHub workflow."""
    found = []
    for line in text.splitlines():
        used = USES.match(line)
        if used and not used.group(1).startswith('./'):
            found.append(_dep('action', used.group(1), used.group(2), source, bool(COMMIT.match(used.group(2)))))
        image = IMAGE.match(line)
        if image:
            reference = image.group(1).strip('"\'')
            name, _, digest = reference.partition('@')
            base, _, tag = name.rpartition(':') if ':' in name.split('/')[-1] else (name, '', 'latest')
            found.append(_dep('image', base, tag + (f'@{digest}' if digest else ''), source, digest.startswith('sha256:')))
    return found


def pip_parts(text, source):
    """The `name==version` requirements of a pip file, pinned when the file carries `--hash=` for them, on the
    requirement's line or on the lines a trailing backslash joins to it (the form a hash-locked file is written in)."""
    found = []
    for line in re.sub(r'\\\n', ' ', text).splitlines():
        match = PIP.match(line.strip())
        if match:
            found.append(_dep('pypi', match.group(1).lower(), match.group(2), source, '--hash=' in line))
    return found


def toolchain_parts(text, source):
    """The tools of the engine's toolchain manifest, each version pinned by its per-architecture checksums."""
    found = []
    for tool, entry in sorted(json.loads(text).items()):
        for version, digests in sorted(entry.get('sha256', {}).items()):
            found.append(_dep('toolchain', tool, version, source, bool(digests)))
    return found


def _dockerfile_instructions(text):
    """Logical Dockerfile instructions: comment lines dropped and backslash continuations joined."""
    instructions, current = [], ''
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.endswith('\\'):
            current += stripped[:-1] + ' '
        else:
            instructions.append((current + stripped).strip())
            current = ''
    if current.strip():
        instructions.append(current.strip())
    return instructions


def dockerfile_parts(text, source):
    """The base images of a Dockerfile (`FROM image`, pinned by a full sha256 digest); `scratch` and earlier build
    stage aliases are not third-party images."""
    found, stages = [], set()
    for line in _dockerfile_instructions(text):
        match = FROM_LINE.match(line)
        if not match:
            continue
        reference, alias = match.group('image'), match.group('alias')
        if reference.lower() != 'scratch' and reference.lower() not in stages:
            name, _, digest = reference.partition('@')
            base, _, tag = name.rpartition(':') if ':' in name.split('/')[-1] else (name, '', 'latest')
            found.append(_dep('image', base, tag + (f'@{digest}' if digest else ''), source, bool(DIGEST.match(digest))))
        if alias:
            stages.add(alias.lower())
    return found


def dockerfile_findings(text, source):
    """Unsafe RUN instructions in a Dockerfile: piping curl/wget output into a shell, or disabling package audit."""
    findings = []
    for line in _dockerfile_instructions(text):
        run = RUN_LINE.match(line)
        if not run:
            continue
        body = run.group(1)
        if CURL_PIPE_SH.search(body):
            findings.append(f'{source}: pipes curl/wget output into a shell; install a checksummed artifact instead')
        if NO_AUDIT.search(body):
            findings.append(f'{source}: uses --no-audit in RUN; keep package audit enabled')
    return findings


def dependencies(root):
    """Every third-party component of the tree, one entry per (ecosystem, name, version), with every file naming it."""
    root = Path(root)
    parts = []
    for name in lockfiles(root):
        parts += lock_packages((root / name).read_text(), name)
    for pattern in WORKFLOWS:
        for path in sorted(root.glob(pattern)):
            parts += workflow_parts(path.read_text(), path.relative_to(root).as_posix())
    for name in dockerfiles(root):
        parts += dockerfile_parts((root / name).read_text(), name)
    for name in pipfiles(root):
        parts += pip_parts((root / name).read_text(), name)
    if (root / TOOLCHAIN).exists():
        parts += toolchain_parts((root / TOOLCHAIN).read_text(), TOOLCHAIN)
    merged = {}
    for part in parts:
        key = (part['ecosystem'], part['name'], part['version'])
        entry = merged.setdefault(key, {**part, 'sources': [], 'pinned': True})
        entry['sources'].append(part['source'])
        entry['pinned'] = entry['pinned'] and part['pinned']
    return [{**entry, 'sources': sorted(set(entry['sources']))} for entry in merged.values()]


def dep_id(ecosystem, name, version):
    return f'DEP:{ecosystem}:{name}@{version}'


def read_snapshot(root):
    path = Path(root) / SNAPSHOT
    return json.loads(path.read_text()) if path.exists() else None


def exemptions(root):
    """{advisory id: exemption} of config/supply/exemptions/."""
    folder = Path(root) / EXEMPTIONS
    return {path.stem: json.loads(path.read_text()) for path in sorted(folder.glob('ADV-*.json'))} if folder.is_dir() else {}


def in_force(exempt, today):
    """Whether an exemption holds: it has a reason and its deadline has not passed. It keeps the check from refusing
    the advisory; it alone does not make the advisory conformant (advisory_state)."""
    return bool(exempt and exempt.get('reason') and exempt.get('deadline', '') >= today)


def advisory_state(advisory, exempt, today):
    """exempted while its exemption is in force and a decision accepts it (authorized_by, D-336), else affecting."""
    if in_force(exempt, today) and exempt.get('authorized_by'):
        return 'exempted'
    return 'affecting'


def utc_today():
    return datetime.now(timezone.utc).date().isoformat()


def suppliers_of(root):
    """({ecosystem: supplier id}, {toolchain tool: supplier id}) from the suppliers' `ecosystems` and `tools`."""
    ecosystems, tools = {}, {}
    for path in sorted(Path(root).glob(SUPPLIERS)):
        body = json.loads(path.read_text())
        for ecosystem in body.get('ecosystems', []):
            ecosystems[ecosystem] = body['id']
        for tool in body.get('tools', []):
            tools[tool] = body['id']
    return ecosystems, tools


def supplier(entry, ecosystems, tools):
    """The supplier id of one component: its tool's supplier, else its ecosystem's; None when no supplier names it."""
    if entry['ecosystem'] == 'toolchain' and entry['name'] in tools:
        return tools[entry['name']]
    return ecosystems.get(entry['ecosystem'])


def _snapshot_date(at):
    """The UTC calendar date of an audit snapshot timestamp (`YYYY-MM-DD...`), else None."""
    if not isinstance(at, str):
        return None
    try:
        return date.fromisoformat(at[:len('YYYY-MM-DD')])
    except ValueError:
        return None


def check(root, today=None):
    """The supply check's refusals: a snapshot taken on other lockfiles or pip files, a stale or undated snapshot, an
    advisory of a blocking severity affecting, an exemption without a reason or a deadline, an unsafe Dockerfile RUN,
    an unpinned component, or a component without a supplier."""
    root, today = Path(root), today or utc_today()
    errors = []
    snapshot = read_snapshot(root)
    present = {name: sha256(root / name) for name in lockfiles(root)}
    present_pips = {name: sha256(root / name) for name in pipfiles(root)}
    if snapshot is None:
        if present or present_pips:
            errors.append(f'{SNAPSHOT}: no audit snapshot; run scripts/supply audit')
    else:
        if snapshot.get('lockfiles', {}) != present:
            errors.append(f'{SNAPSHOT}: taken on other lockfiles than the tree has; run scripts/supply audit')
        if present_pips and snapshot.get('pipfiles', {}) != present_pips:
            errors.append(f'{SNAPSHOT}: taken on other pip files than the tree has; run scripts/supply audit')
        max_days = setting('supply.snapshot_max_days')
        taken = _snapshot_date(snapshot.get('at'))
        if taken is None:
            errors.append(f'{SNAPSHOT}: missing or invalid audit timestamp `at`; run scripts/supply audit')
        else:
            age = (date.fromisoformat(today) - taken).days
            if age > max_days:
                errors.append(f'{SNAPSHOT}: audit snapshot is {age} day(s) old (at {snapshot["at"]}, max {max_days}); '
                              f'run scripts/supply audit')
        granted = exemptions(root)
        import json_schema
        schema = json.loads((ROOT / 'contracts/model/exemption.v1.json').read_text())
        for name, body in granted.items():
            problems = list(json_schema.validate(schema, body)) + ([] if body.get('id') == name else ['its id must equal the file name'])
            errors += [f'{EXEMPTIONS}/{name}.json: {problem}' for problem in problems]
        blocking = set(setting('supply.blocking_severities'))
        for advisory in snapshot.get('advisories', []):
            exempt = granted.get(advisory['id'])
            if advisory['severity'] in blocking and not in_force(exempt, today):
                errors.append(f'{advisory["id"]}: {advisory["severity"]} advisory on {advisory["package"]} '
                              f'{", ".join(advisory["versions"])} is affecting (patched: {advisory["patched"]}); update the '
                              f'package or exempt it with a reason and a deadline')
        stray = sorted(set(granted) - {advisory['id'] for advisory in snapshot.get('advisories', [])})
        errors += [f'{EXEMPTIONS}/{name}.json: exempts an advisory the snapshot does not have; remove it' for name in stray]
    for name in dockerfiles(root):
        errors += dockerfile_findings((root / name).read_text(), name)
    deps = dependencies(root)
    for entry in deps:
        if not entry['pinned']:
            errors.append(f'{", ".join(entry["sources"])}: unpinned {entry["ecosystem"]} component '
                          f'{entry["name"]}@{entry["version"]}; pin it by integrity, digest, commit or hash')
    ecosystems, tools = suppliers_of(root)
    missing = sorted({entry['ecosystem'] for entry in deps if supplier(entry, ecosystems, tools) is None})
    errors += [f'ecosystem {name}: no supplier in config/supply/suppliers names it' for name in missing]
    return errors


def advisory_id(ghsa):
    return 'ADV-' + ghsa.lower()


def from_audit(report, lockfile):
    """The advisories of one `pnpm audit --json` report, each with the installed versions it affects."""
    found = []
    for advisory in report.get('advisories', {}).values():
        ghsa = advisory.get('github_advisory_id') or f'npm-{advisory["id"]}'
        versions = sorted({finding['version'] for finding in advisory.get('findings', [])})
        found.append({'id': advisory_id(ghsa), 'ghsa': ghsa, 'ecosystem': 'npm', 'package': advisory['module_name'],
                      'versions': versions, 'vulnerable': advisory['vulnerable_versions'],
                      'patched': advisory['patched_versions'], 'severity': advisory['severity'],
                      'title': advisory['title'], 'url': advisory.get('url', ''), 'lockfiles': [lockfile]})
    return found


OSV_SEVERITIES = {'critical': 'critical', 'high': 'high', 'moderate': 'moderate', 'medium': 'moderate', 'low': 'low'}


def _osv_fetch(url, payload=None):
    """One HTTPS JSON request to the configured OSV endpoint."""
    if urllib.parse.urlparse(url).scheme != 'https':
        raise ValueError(f'OSV URL must use https: {url}')
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=setting('supply.osv_timeout_s')) as response:
        return json.loads(response.read().decode())


def _osv_severity(record):
    """Map an OSV vulnerability record's severity to supply's scale; unknown defaults to high (fail closed)."""
    raw = (record.get('database_specific') or {}).get('severity')
    if not raw:
        for affected in record.get('affected') or ():
            raw = (affected.get('ecosystem_specific') or {}).get('severity') or (affected.get('database_specific') or {}).get('severity')
            if raw:
                break
    return OSV_SEVERITIES.get(str(raw).lower(), 'high') if raw else 'high'


def _osv_patched(record, package):
    """The fixed version constraints of an OSV record for `package`, else `none`."""
    fixed = set()
    for affected in record.get('affected') or ():
        pkg = (affected.get('package') or {}).get('name', '').lower()
        if pkg and pkg != package.lower():
            continue
        for span in affected.get('ranges') or ():
            for event in span.get('events') or ():
                if event.get('fixed'):
                    fixed.add(event['fixed'])
    return ', '.join(f'>={version}' for version in sorted(fixed)) if fixed else 'none'


def from_osv(records, hits):
    """Convert OSV vulnerability records and `(package, version, sources, vuln_id)` hits into snapshot advisories."""
    merged = {}
    for package, version, sources, vuln_id in hits:
        record = records.get(vuln_id) or {'id': vuln_id}
        aliases = record.get('aliases') or ()
        ghsa = next((alias for alias in aliases if alias.startswith('GHSA-')), vuln_id)
        ident = advisory_id(ghsa)
        refs = [ref.get('url', '') for ref in record.get('references') or () if ref.get('url')]
        entry = {'id': ident, 'ghsa': ghsa, 'ecosystem': 'pypi', 'package': package, 'versions': [version],
                 'vulnerable': f'=={version}', 'patched': _osv_patched(record, package),
                 'severity': _osv_severity(record), 'title': record.get('summary') or vuln_id,
                 'url': refs[0] if refs else '', 'lockfiles': sorted(sources)}
        current = merged.setdefault(ident, entry)
        if current is not entry:
            current['versions'] = sorted(set(current['versions']) | set(entry['versions']))
            current['lockfiles'] = sorted(set(current['lockfiles']) | set(entry['lockfiles']))
    return list(merged.values())


def audit_pypi(root, fetch=None):
    """Audit pinned PyPI requirements in `pipfiles(root)` against OSV (`supply.osv_url`)."""
    root = Path(root)
    packages = {}
    for name in pipfiles(root):
        for entry in pip_parts((root / name).read_text(), name):
            packages.setdefault((entry['name'], entry['version']), set()).add(name)
    if not packages:
        return []
    fetch = fetch or _osv_fetch
    base = setting('supply.osv_url').rstrip('/')
    ordered = sorted(packages)
    response = fetch(f'{base}/querybatch', {'queries': [{'package': {'name': name, 'ecosystem': 'PyPI'}, 'version': version}
                                                        for name, version in ordered]})
    results = response.get('results')
    if not isinstance(results, list) or len(results) != len(ordered):
        raise RuntimeError('OSV querybatch gave an incomplete response')
    hits, needed = [], set()
    for (name, version), item in zip(ordered, results):
        for vuln in item.get('vulns') or ():
            vuln_id = vuln.get('id')
            if vuln_id:
                hits.append((name, version, packages[(name, version)], vuln_id))
                needed.add(vuln_id)
    records = {vuln_id: fetch(f'{base}/vulns/{vuln_id}', None) for vuln_id in sorted(needed)}
    return from_osv(records, hits)


def _merge_advisories(merged, advisories):
    for advisory in advisories:
        current = merged.setdefault(advisory['id'], advisory)
        if current is not advisory:
            current['versions'] = sorted(set(current['versions']) | set(advisory['versions']))
            current['lockfiles'] = sorted(set(current['lockfiles']) | set(advisory['lockfiles']))


def audit(root, run=subprocess.run, now=None, fetch=None):
    """The snapshot of every lockfile's (pnpm audit) and pip file's (OSV) advisories."""
    root = Path(root)
    merged = {}
    for name in lockfiles(root):
        result = run(['pnpm', 'audit', '--json'], cwd=root / Path(name).parent, capture_output=True, text=True)
        report = json.loads(result.stdout or '{}')
        if 'advisories' not in report:
            raise RuntimeError(f'{name}: pnpm audit gave no report ({result.stderr.strip()[:200]})')
        _merge_advisories(merged, from_audit(report, name))
    _merge_advisories(merged, audit_pypi(root, fetch=fetch))
    return {'generated_by': 'scripts/supply audit',
            'at': now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'lockfiles': {name: sha256(root / name) for name in lockfiles(root)},
            'pipfiles': {name: sha256(root / name) for name in pipfiles(root)},
            'advisories': sorted(merged.values(), key=lambda item: item['id'])}


def measure(root, today=None):
    """The supply system's own measure: components by ecosystem and pinned origin, advisories by state and severity."""
    today = today or utc_today()
    deps = dependencies(root)
    snapshot = read_snapshot(root) or {'advisories': []}
    granted = exemptions(root)
    by_state = {}
    for advisory in snapshot['advisories']:
        state = advisory_state(advisory, granted.get(advisory['id']), today)
        key = f'{state}:{advisory["severity"]}'
        by_state[key] = by_state.get(key, 0) + 1
    ecosystems = {}
    for entry in deps:
        counted = ecosystems.setdefault(entry['ecosystem'], {'components': 0, 'pinned': 0})
        counted['components'] += 1
        counted['pinned'] += entry['pinned']
    return {'components': len(deps), 'pinned': sum(entry['pinned'] for entry in deps),
            'ecosystems': dict(sorted(ecosystems.items())), 'advisories': dict(sorted(by_state.items())),
            'snapshot_at': (read_snapshot(root) or {}).get('at')}


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/supply', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('audit', help='refresh the advisory snapshot (pnpm audit; reaches the network)')
    commands.add_parser('check', help='judge the tree against the snapshot, with no network')
    commands.add_parser('measure', help='the supply system measure')
    args = parser.parse_args(argv)
    if args.command == 'audit':
        made = audit(root)
        (Path(root) / SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / SNAPSHOT).write_text(json.dumps(made, indent=1, ensure_ascii=False) + '\n')
        print(f'supply audit: {len(made["advisories"])} advisory(ies) on {len(made["lockfiles"])} lockfile(s) -> {SNAPSHOT}')
        return 0
    if args.command == 'measure':
        print(json.dumps(measure(root), indent=1))
        return 0
    errors = check(root)
    for error in errors:
        print(f'FAIL {error}')
    print(f'supply check: {len(errors)} refusal(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
