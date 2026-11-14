#!/usr/bin/env python3
"""RETRO-API: the store that receives each session's log and keeps it (Daniel 2026-10-28 20:00 BRT; D-054).

Receive and keep, nothing else: no summary, no analysis, no score. What is done with the logs is decided later.

Store layout (docs/units/RETRO-API/audit.md, store decision): the root is $TOWER_RETRO_STORE, else <checkout>/retro
(gitignored). A log lands at logs/<unit>/<session>.<ext>, or logs/<unit>/<session>.<kind>.<ext> for a motor record;
a name already taken by other bytes gets the digest before the extension, so nothing is ever
overwritten. Line 1 is the header (one JSON object: retro, v, unit, session, kind, source, bytes, sha256, stored);
the rest is the file exactly as the session produced it, byte for byte. A log over retro.max_file_bytes is kept as the
header alone with stored "pointer" (the source path and the digest); a log is never truncated.

Before anything is written the file is scanned with the repo's own secret patterns (gitleaks with
local-checks.gitleaks_config, --redact), extended only by retro.scan_allowlist (one exception: the UUID Claude Code
writes as turnAttributionKey on every transcript). A hit refuses the file and names the rule and the line:column offset, never
the value. Without gitleaks there is no scan, and the file is refused.

The index is <root>/index.jsonl, one line per stored file (unit, session, kind, path, source, bytes, sha256, stored,
received_at); it is the only derived thing. keep() is idempotent by digest: bytes whose sha256 is already indexed are
not stored again. A lock file serializes writers.

CLI (scripts/retro):
  ingest --unit <id> [--session <sid>]   copy the logs already on this box: the Claude Code transcript
      ($CLAUDE_CONFIG_DIR or ~/.claude, projects/*/<sid>.jsonl; without --session every transcript whose gitBranch is
      mod/<unit lowercase>) and the unit's motor records under $TOWER_MOTOR_DIR or retro.motor_dir:
      the lines of sessions.log and claims* that name the unit, and any other file whose name names it (a tmux
      capture). One line per file: what it took, from where, how many bytes. Exit 1 when a file was refused.
  receive --unit <id> --session <sid> [--path <file>]   keep one transcript a caller hands in (the file, else stdin):
      the shape a future API call uses. It must parse as Claude Code JSONL; nothing is added to it. Exit 1 when refused.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import config  # noqa: E402

HEADER = 'header'
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
KINDS = {'transcript': 'jsonl', 'motor': 'log'}


class Refused(Exception):
    """The file is not stored; the message says why without quoting the content."""


def store_root():
    return Path(os.environ.get('TOWER_RETRO_STORE') or ROOT / 'retro')


def max_file_bytes():
    return config.get('retro.max_file_bytes')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _gitleaks():
    local = ROOT / '.toolchain' / 'bin' / 'gitleaks'
    return shutil.which('gitleaks') or (str(local) if local.is_file() else None)


def _toml_literal(text):
    if "'''" in text:
        raise Refused('no secret scan: a retro.scan_allowlist entry cannot be written as a TOML literal')
    return f"'''{text}'''"


def _scan_config(folder):
    """The repo's gitleaks config, extended with retro.scan_allowlist; the repo-wide scan is not changed."""
    lines = []
    repo = ROOT / config.get('local-checks.gitleaks_config')
    lines += ['[extend]', f'path = {_toml_literal(str(repo))}'] if repo.is_file() else ['[extend]', 'useDefault = true']
    for entry in config.get('retro.scan_allowlist'):
        lines += ['', '[[allowlists]]', f'description = {_toml_literal(entry["description"])}',
                  'regexTarget = "match"', f'regexes = [{_toml_literal(entry["regex"])}]']
    path = folder / 'retro-gitleaks.toml'
    path.write_text('\n'.join(lines) + '\n')
    return path


def secret_findings(data, name='log'):
    """The repo's secret patterns over these bytes: [(rule, line, column)], never the value. Raises Refused when the
    scan cannot run."""
    tool = _gitleaks()
    if not tool:
        raise Refused('no secret scan: gitleaks is not installed (bash scripts/cloud/setup.sh)')
    with tempfile.TemporaryDirectory() as tmp:
        tree, report = Path(tmp) / 'tree', Path(tmp) / 'report.json'
        tree.mkdir()
        (tree / name).write_bytes(data)
        command = [tool, 'dir', '--redact', '--no-banner', '--report-format', 'json', '--report-path', str(report),
                   '--config', str(_scan_config(Path(tmp)))]
        try:
            done = subprocess.run(command + ['.'], cwd=tree, capture_output=True, text=True,
                                  timeout=config.get('local-checks.gitleaks_timeout_s'))
        except subprocess.TimeoutExpired:
            raise Refused('no secret scan: gitleaks timed out')
        if done.returncode == 0:
            return []
        try:
            hits = json.loads(report.read_text())
        except (OSError, ValueError):
            raise Refused(f'no secret scan: gitleaks failed (exit {done.returncode})')
    return [(hit.get('RuleID', '?'), hit.get('StartLine', '?'), hit.get('StartColumn', '?')) for hit in hits]


def shape_errors(data, kind):
    """Why these bytes are not a log of this kind ([] when they are). A transcript is Claude Code JSONL: every
    non-empty line a JSON object with a string type. A motor record is UTF-8 text."""
    if not data.strip():
        return ['empty']
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        return [f'not UTF-8 at byte {error.start}']
    if kind != 'transcript':
        return []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            return [f'line {number} is not JSON']
        if not isinstance(item, dict) or not isinstance(item.get('type'), str):
            return [f'line {number} is not a transcript entry (a JSON object with a string type)']
    return []


def _target(folder, stem, ext, digest):
    plain = folder / f'{stem}.{ext}'
    return plain if not plain.exists() else folder / f'{stem}.{digest}.{ext}'


def store(unit, session, kind, source, data, root=None):
    """Keep one log: refuse a bad id, a wrong shape or a secret; write header + bytes. Returns the header."""
    for label, value in (('unit', unit), ('session', session)):
        if not ID.match(value or ''):
            raise Refused(f'{label} id {value!r} is not a plain id ([A-Za-z0-9._-], at most 128)')
    if kind not in KINDS:
        raise Refused(f'kind {kind!r} is not one of {sorted(KINDS)}')
    problems = shape_errors(data, kind)
    if problems:
        raise Refused(f'not a {kind} log ({problems[0]})')
    hits = secret_findings(data)
    if hits:
        where = ', '.join(f'{rule} at line {line}:{column}' for rule, line, column in hits)
        raise Refused(f'carries a secret ({where}; value not shown)')
    root = Path(root or store_root())
    digest = sha256(data)
    folder = root / 'logs' / unit
    folder.mkdir(parents=True, exist_ok=True)
    stem = session if kind == 'transcript' else f'{session}.{kind}'
    path = _target(folder, stem, KINDS[kind], digest)
    pointer = len(data) > max_file_bytes()
    header = {'retro': HEADER, 'v': 1, 'unit': unit, 'session': session, 'kind': kind, 'source': str(source),
              'bytes': len(data), 'sha256': digest, 'stored': 'pointer' if pointer else 'bytes'}
    line = (json.dumps(header, sort_keys=True) + '\n').encode()
    with open(path, 'xb') as handle:  # never overwrite: append-only by construction
        handle.write(line if pointer else line + data)
    header['path'] = path.relative_to(root).as_posix()
    return header


def index_path(root=None):
    return Path(root or store_root()) / 'index.jsonl'


def indexed(root=None):
    """The index lines, oldest first ([] before the first store)."""
    path = index_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


@contextmanager
def _locked(root):
    root.mkdir(parents=True, exist_ok=True)
    with open(root / '.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def keep(unit, session, kind, source, data, root=None, now=None):
    """Store one log and index it. Returns the index line, or None when these bytes are already stored."""
    root = Path(root or store_root())
    with _locked(root):
        digest = sha256(data)
        if any(line.get('sha256') == digest for line in indexed(root)):
            return None
        header = store(unit, session, kind, source, data, root=root)
        moment = now or datetime.now(timezone.utc)
        entry = {key: header[key] for key in ('unit', 'session', 'kind', 'path', 'source', 'bytes', 'sha256', 'stored')}
        entry['received_at'] = moment.isoformat(timespec='seconds')
        with open(index_path(root), 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, sort_keys=True) + '\n')
        return entry


def claude_dir():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')


def motor_dir():
    return Path(os.environ.get('TOWER_MOTOR_DIR') or config.get('retro.motor_dir'))


def _on_branch(path, branch):
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get('gitBranch') == branch:
                return True
    return False


def transcripts(unit, session=None, home=None):
    """[(session, path)] of the Claude Code transcripts on this box for the unit."""
    projects = Path(home or claude_dir()) / 'projects'
    if session:
        return [(session, path) for path in sorted(projects.glob(f'*/{session}.jsonl'))]
    branch = f'mod/{unit.lower()}'
    return [(path.stem, path) for path in sorted(projects.glob('*/*.jsonl')) if _on_branch(path, branch)]


def motor_records(unit, motor=None):
    """[(source label, bytes)] of the unit's motor records: the lines of sessions.log and claims* naming the unit,
    and every other file whose name names it, whole."""
    motor = Path(motor or motor_dir())
    if not motor.is_dir():
        return []
    names = re.compile(rf'(?<![A-Za-z0-9-]){re.escape(unit)}(?![A-Za-z0-9-])')
    found = []
    for path in sorted(item for item in motor.rglob('*') if item.is_file()):
        if path.name == 'sessions.log' or path.name.startswith('claims'):
            lines = [line for line in path.read_bytes().splitlines(keepends=True)
                     if names.search(line.decode('utf-8', errors='replace'))]
            if lines:
                found.append((f'{path} (lines naming {unit})', b''.join(lines)))
        elif names.search(path.name):
            found.append((str(path), path.read_bytes()))
    return found


def _take(unit, session, kind, source, data, root, out):
    try:
        entry = keep(unit, session, kind, source, data, root=root)
    except Refused as error:
        print(f'refused {source}: {error}', file=out)
        return False
    if entry is None:
        print(f'skipped {source}: already stored (sha256 {sha256(data)})', file=out)
    else:
        print(f'took {entry["path"]} from {source} ({entry["bytes"]} bytes, stored {entry["stored"]})', file=out)
    return True


def ingest(unit, session=None, root=None, home=None, motor=None, out=None):
    """Copy the unit's logs already on this box into the store. Returns False when any file was refused."""
    out = out or sys.stdout
    ok = True
    found = transcripts(unit, session, home)
    if not found:
        print(f'no transcript for {unit}{f" session {session}" if session else ""} under {Path(home or claude_dir())}/projects',
              file=out)
    for sid, path in found:
        ok = _take(unit, sid, 'transcript', str(path), path.read_bytes(), root, out) and ok
    motor = Path(motor or motor_dir())
    if not motor.is_dir():
        print(f'no motor records: {motor} is not on this box', file=out)
    for source, data in motor_records(unit, motor):
        ok = _take(unit, session or 'motor', 'motor', source, data, root, out) and ok
    return ok


def receive(unit, session, path=None, root=None, stdin=None, out=None):
    """Keep one transcript handed in by a caller. Returns False when it was refused."""
    out = out or sys.stdout
    if path:
        source = str(Path(path).resolve())
        try:
            data = Path(path).read_bytes()
        except OSError as error:
            print(f'refused {path}: cannot be read ({error.strerror})', file=out)
            return False
    else:
        source, data = '<stdin>', (stdin or sys.stdin.buffer).read()
    return _take(unit, session, 'transcript', source, data, root, out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/retro', description='RETRO-API: receive and keep session logs.')
    commands = parser.add_subparsers(dest='command', required=True)
    take = commands.add_parser('ingest', help='copy the logs of a unit already on this box into the store')
    take.add_argument('--unit', required=True)
    take.add_argument('--session')
    door = commands.add_parser('receive', help='keep one transcript a caller hands in (file or stdin)')
    door.add_argument('--unit', required=True)
    door.add_argument('--session', required=True)
    door.add_argument('--path')
    args = parser.parse_args(argv)
    if args.command == 'ingest':
        return 0 if ingest(args.unit, args.session) else 1
    return 0 if receive(args.unit, args.session, args.path) else 1


if __name__ == '__main__':
    sys.exit(main())
