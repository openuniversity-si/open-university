"""The known-defect registry (KD1, D-069 items 4, 8 and 9): a test that fails on the integration base, recorded once.

A defect is docs/process/defects/<slug>.yml (strict YAML subset, shape contracts/defects/defect.v2.json) and its audit
trail <slug>.audit.jsonl (contracts/defects/audit.v1.json): one line per change, only ever appended, each line carrying
the digest of the one before. The id is a hash of (test id, normalized signature), so a defect has one id on every branch
and a second sighting is a dedup, not a second record. The unit, owner and area are derived from the unit manifests
every time a record is loaded and are never stored (DERIVED; the record schema has no such fields), so a merge that
moves a unit's paths leaves no record stale. Every name, suffix, status and
transition is a defects.* registry entry (D-068).

  record(root, ...)      open a defect, or add evidence to the one with the same (test, signature); a resolved or
                         verified defect seen failing again is reopened
  transition(root, ...)  change the status along defects.transitions, with who and why in the trail
  load(root)             (records by id, errors): schema, chain, filename, dedup; adds the derived unit/owner/area
  check(root, base=None) load's errors plus: no trail may lose an entry the base ref already has

scripts/defects list|show|record|resolve|check (this module); the router and the verification are
scripts/lib/defect_router.py and scripts/lib/defect_detect.py.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import config
import forge_events
import json_schema
import premises
import units

ROOT = Path(__file__).resolve().parents[2]
HEADER = '# Known defect record (D-069 items 4, 8 and 9, contracts/defects/defect.v2.json). Change it with scripts/defects; the trail is append-only.'
SLUG_PART = re.compile(r'[^a-z0-9]+')


class DefectError(ValueError):
    pass


def setting(name):
    return config.get(f'defects.{name}')


def register_dir(root=ROOT):
    return Path(root) / setting('register_dir')


def _schema(name, root):
    return json.loads((Path(root) / setting(name)).read_text(encoding='utf-8'))


def short(sha):
    """A sha as the trail notes print it."""
    return sha[:12]


def defect_id(test, signature):
    material = f'{test}\0{signature}'.encode()
    return setting('id_prefix') + hashlib.new(setting('digest_algorithm'), material).hexdigest()[:setting('id_hash_chars')]


def slug_of(test, ident):
    stem = SLUG_PART.sub('-', test.lower()).strip('-')
    return f'{stem}-{ident[len(setting("id_prefix")):]}'


def paths(root, slug):
    base = register_dir(root) / slug
    return base.with_name(slug + setting('record_suffix')), base.with_name(slug + setting('audit_suffix'))


DERIVED = ('unit', 'owner', 'area')  # derive_owner's fields: filled in by load, stripped by write


def derive_owner(test, root=ROOT, files=None):
    """(unit, owner, area) of the file a test id names, from the unit manifests; unowned tests get defects.unknown_owner."""
    if files is None:
        listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
        files = {name.decode() for name in listed.split(b'\0') if name}
    prefixes = config.get('quarantine.test_roots')  # OU-DECOUPLE F5 (D-113): the registry's prefixes, not a product path
    for token in test.split(' > ', 1)[0].split():
        for candidate in (prefix + token for prefix in prefixes):
            if candidate in files:
                unit = units.unit_of(candidate, root)
                if unit:
                    manifest = units.manifests(root)[unit]
                    return unit, units.owner_of(unit, root), list(manifest['paths'])
    return None, setting('unknown_owner'), []


def entry_digest(entry):
    body = {key: value for key, value in entry.items() if key != 'digest'}
    return hashlib.new(setting('digest_algorithm'), json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def append_entry(trail, by, action, old, new, note, at):
    """The trail with one more entry chained to the last."""
    prev = trail[-1]['digest'] if trail else setting('genesis_digest')
    entry = {'n': len(trail) + 1, 'at': at, 'by': by, 'action': action, 'from': old, 'to': new, 'note': note, 'prev': prev}
    entry['digest'] = entry_digest(entry)
    return trail + [entry]


def chain_errors(trail, name):
    errors, prev = [], setting('genesis_digest')
    for index, entry in enumerate(trail, 1):
        if entry.get('n') != index:
            errors.append(f'{name}: entry {index} is numbered {entry.get("n")}')
        if entry.get('prev') != prev:
            errors.append(f'{name}: entry {index} does not continue the chain (an entry was edited or removed)')
        if entry.get('digest') != entry_digest(entry):
            errors.append(f'{name}: entry {index} was edited (its digest differs)')
        prev = entry.get('digest')
    return errors


def read_trail(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def dump(record, root=ROOT):
    return premises.dump(record, _schema('record_schema', root)).replace(premises.HEADER, HEADER, 1)


def write(root, record, trail):
    record_path, trail_path = paths(root, record['slug'])
    record_path.parent.mkdir(parents=True, exist_ok=True)
    stored = {key: value for key, value in record.items() if key not in DERIVED and key != 'trail'}
    record_path.write_text(dump(stored, root), encoding='utf-8')
    trail_path.write_text(''.join(json.dumps(entry, sort_keys=True) + '\n' for entry in trail), encoding='utf-8')


def load(root=ROOT, files=None):
    """(records by id, errors). Every record carries its trail under 'trail' in memory only."""
    root = Path(root)
    found, errors, keys = {}, [], {}
    if not register_dir(root).is_dir():
        return found, errors
    shape, audit = _schema('record_schema', root), _schema('audit_schema', root)
    for path in sorted(register_dir(root).glob('*' + setting('record_suffix'))):
        name = path.relative_to(root).as_posix()
        try:
            record = premises.parse(path.read_text(encoding='utf-8'), name)
            trail = read_trail(path.with_name(path.name[:-len(setting('record_suffix'))] + setting('audit_suffix')))
        except (premises.FormatError, ValueError) as error:
            errors.append(str(error))
            continue
        problems = [f'{name}: {message}' for message in json_schema.errors(record, shape)]
        for number, entry in enumerate(trail, 1):
            problems += [f'{name} trail {number}: {message}' for message in json_schema.errors(entry, audit)]
        if problems:
            errors += problems
            continue
        errors += chain_errors(trail, name)
        if record['id'] != defect_id(record['test'], record['signature']):
            errors.append(f'{name}: id {record["id"]} is not the hash of its test and signature')
        if path.stem != slug_of(record['test'], record['id']) or record['slug'] != path.stem:
            errors.append(f'{name}: the file name must be {slug_of(record["test"], record["id"])}')
        if record['status'] not in setting('statuses'):
            errors.append(f'{name}: status {record["status"]} is not one of {setting("statuses")}')
        if not trail or trail[-1]['to'] != record['status']:
            errors.append(f'{name}: the last trail entry must end in the record status {record["status"]}')
        record.update(zip(DERIVED, derive_owner(record['test'], root, files)))
        key = (record['test'], record['signature'])
        if key in keys:
            errors.append(f'{name}: duplicates {keys[key]} (same test and signature)')
        keys[key] = name
        record['trail'] = trail
        found[record['id']] = record
    return found, errors


def check(root=ROOT, base=None):
    """load's errors, plus: against `base` (a git ref) no trail may drop or change an entry the base already holds."""
    records, errors = load(root)
    if base:
        listed = subprocess.run(['git', '-C', str(root), 'ls-tree', '-r', '--name-only', base, setting('register_dir')],
                                capture_output=True, text=True)
        for name in listed.stdout.split():
            if not name.endswith(setting('audit_suffix')):
                continue
            old = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{name}'], capture_output=True, text=True).stdout
            new = Path(root, name)
            kept = new.read_text(encoding='utf-8') if new.is_file() else ''
            if not kept.startswith(old):
                errors.append(f'{name}: the trail is append-only; the base holds entries this version lost or changed')
    return records, errors


def now(clock=None):
    return forge_events.rfc3339((clock or forge_events.clock_from_config()).now())


def emit(port, kind, record, root, sha, extra):
    if port is None:
        return None
    subject = forge_events.subject(config.get('forge-events.repo'), None, sha, (), record['unit'])
    base = {'defect': record['id'], 'test': record['test'], 'signature': record['signature'], 'owner': record['owner']}
    return port.emit(kind, dict(subject, **base, **extra))


def record(root, test, stage, signature, base_sha, run, by, summary=None, port=None, clock=None, files=None):
    """(record, 'created' | 'observed' | 'reopened'). The same (test, signature) is the same defect."""
    ident = defect_id(test, signature)
    stamp = now(clock)
    proof = {'base_sha': base_sha, 'run': run, 'result': 'fail', 'signature': signature, 'at': stamp}
    existing, errors = load(root, files)
    if errors:
        raise DefectError('; '.join(errors))
    if ident in existing:
        current = existing[ident]
        trail = current.pop('trail')
        seen = {(item['base_sha'], item['run']) for item in current['evidence']}
        if (base_sha, run) in seen:
            current['trail'] = trail
            return current, 'observed'
        current['evidence'] = current['evidence'] + [proof]
        if current['status'] in ('resolved', 'verified'):
            trail = append_entry(trail, by, 'reopened', current['status'], 'open', f'failed again on {short(base_sha)} ({run})', stamp)
            current['status'] = 'open'
            emit(port, 'defect.reopened', current, root, base_sha, {'base_sha': base_sha, 'observed_signature': signature, 'run': run})
            write(root, {k: v for k, v in current.items() if k != 'trail'}, trail)
            current['trail'] = trail
            return current, 'reopened'
        trail = append_entry(trail, by, 'observed', current['status'], current['status'], f'failed on {short(base_sha)} ({run})', stamp)
        write(root, {k: v for k, v in current.items() if k != 'trail'}, trail)
        current['trail'] = trail
        return current, 'observed'
    unit, owner, area = derive_owner(test, root, files)
    new = {'id': ident, 'slug': slug_of(test, ident), 'test': test, 'stage': stage, 'signature': signature,
           'summary': summary or signature, 'status': setting('statuses')[0], 'owner': owner, 'unit': unit, 'area': area,
           'evidence': [proof], 'fix': None}
    trail = append_entry([], by, 'registered', None, new['status'], f'failed on {short(base_sha)} ({run})', stamp)
    write(root, new, trail)
    emit(port, 'defect.registered', new, root, base_sha, {'area': area})
    return dict(new, trail=trail), 'created'


def transition(root, ident, to, by, note, fix=None, clock=None, action=None):
    """Move a defect along defects.transitions; the trail names who, when and why."""
    records, errors = load(root)
    if errors:
        raise DefectError('; '.join(errors))
    if ident not in records:
        raise DefectError(f'unknown defect {ident}')
    current = records[ident]
    trail = current.pop('trail')
    if f'{current["status"]}>{to}' not in setting('transitions'):
        raise DefectError(f'{ident}: {current["status"]} cannot become {to} (defects.transitions)')
    action = action or {'fixing': 'routed', 'resolved': 'resolved', 'verified': 'verified', 'open': 'reopened'}[to]
    trail = append_entry(trail, by, action, current['status'], to, note, now(clock))
    current['status'] = to
    if fix is not None:
        current['fix'] = fix
    write(root, current, trail)
    current['trail'] = trail
    return current


def resolve(root, ident, pr, merge_sha, by, port=None, clock=None):
    """fixing -> resolved when the fix unit's PR merged; the gate verifies it on the base afterwards."""
    records, errors = load(root)
    if errors:
        raise DefectError('; '.join(errors))
    if ident not in records:
        raise DefectError(f'unknown defect {ident}')
    current = records[ident]
    if not current['fix']:
        raise DefectError(f'{ident}: no fix unit was opened for it (status {current["status"]})')
    fix = dict(current['fix'], pr=pr, merge_sha=merge_sha)
    done = transition(root, ident, 'resolved', by, f'fix PR #{pr} merged as {short(merge_sha)}', fix=fix, clock=clock)
    emit(port, 'defect.resolved', done, root, merge_sha, {'fix_pr': pr, 'merge_sha': merge_sha})
    return done


def sync(root, events, port=None, clock=None):
    """Apply the gate's defect events (the repository log) to the registry; [(defect, what)] for each change made.

    The gate runs in a PR checkout and only publishes: detected -> record, verified -> verified (an open record ->
    resolved, GX-13 defects.verify_open), reopened -> open. Every
    step is idempotent, so replaying the same log changes nothing."""
    done = []
    with port.batched() if port is not None else contextlib.nullcontext():  # GX-FIX-forge-rate: one append
        for event in forge_events.dedupe(events)[0]:
            kind, body, by = event['type'], event['payload'], event['producer']
            if kind == 'defect.detected':
                found, outcome = record(root, body['test'], body['stage'], body['signature'], body['base_sha'], body['run'], by,
                                        port=port, clock=clock)
                done.append((found['id'], outcome))
                continue
            current = load(root)[0].get(body['defect'])
            if kind == 'defect.verified' and current and current['status'] == 'resolved':
                transition(root, body['defect'], 'verified', by, f'passes on the base {short(body["base_sha"])} ({body["run"]})', clock=clock)
                done.append((body['defect'], 'verified'))
            elif kind == 'defect.verified' and current and current['status'] == 'open' and setting('verify_open'):
                # GX-13: an open defect that no longer reproduces on the recorded base; a later pass verifies it.
                transition(root, body['defect'], 'resolved', by, f'no longer reproduces on the base {short(body["base_sha"])} ({body["run"]})', clock=clock)
                done.append((body['defect'], 'resolved'))
            elif kind == 'defect.reopened' and current and current['status'] in ('resolved', 'verified'):
                transition(root, body['defect'], 'open', by, f'fails on the base {short(body["base_sha"])} ({body["run"]}): {body["observed_signature"]}', clock=clock)
                done.append((body['defect'], 'reopened'))
    return done


def render(records, columns=None):
    columns = columns or setting('list_columns')
    rows = [[str(record.get(column) or '-') for column in columns] for record in sorted(records.values(), key=lambda r: r['id'])]
    widths = [max(len(column), *(len(row[i]) for row in rows)) if rows else len(column) for i, column in enumerate(columns)]
    lines = ['  '.join(column.ljust(widths[i]) for i, column in enumerate(columns))]
    return lines + ['  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]


def show(record):
    lines = [f'{key}: {json.dumps(record[key], ensure_ascii=False)}' for key in record if key != 'trail']
    return lines + [f'trail {entry["n"]}: {entry["at"]} {entry["by"]} {entry["action"]} {entry["from"]}>{entry["to"]} {entry["note"]}'
                    for entry in record['trail']]


def _port(producer, correlation):
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(), producer, correlation)


def argv_tail(args):
    extra = [flag for name in ('base_sha', 'by') if getattr(args, name, None) for flag in (f'--{name.replace("_", "-")}', getattr(args, name))]
    return [args.command, *extra]


def main(argv=None, root=ROOT, port=None):
    parser = argparse.ArgumentParser(prog='scripts/defects', description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=str(root))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    shown = sub.add_parser('show'); shown.add_argument('id')
    rec = sub.add_parser('record')
    for flag in ('test', 'stage', 'signature', 'base-sha', 'run', 'by'):
        rec.add_argument('--' + flag, required=True)
    rec.add_argument('--summary'); rec.add_argument('--no-emit', action='store_true')
    res = sub.add_parser('resolve')
    res.add_argument('id'); res.add_argument('--pr', type=int, required=True); res.add_argument('--merge-sha', required=True)
    res.add_argument('--by', required=True); res.add_argument('--no-emit', action='store_true')
    sub.add_parser('sync')
    sub.add_parser('priority')
    walk = sub.add_parser('route'); walk.add_argument('--base-sha'); walk.add_argument('--by')
    chk = sub.add_parser('check'); chk.add_argument('--base')
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == 'list':
            records, errors = load(root)
            print('\n'.join(render(records)))
        elif args.command == 'show':
            records, errors = load(root)
            if args.id not in records:
                raise DefectError(f'unknown defect {args.id}')
            print('\n'.join(show(records[args.id])))
        elif args.command == 'check':
            records, errors = check(root, args.base)
            print(f'defects: {len(records)} record(s), {len(errors)} error(s)')
        elif args.command in ('route', 'priority'):
            import defect_router  # imports this module; loaded only for these commands
            return defect_router.main(argv_tail(args), root, port)
        elif args.command == 'sync':
            port = port or _port(setting('producer'), f'{setting("producer")}:sync')
            changes = sync(root, port.read_recent(config.get('forge-events.repo')), port)  # D-085: the shared window
            print('\n'.join(f'{ident} {what}' for ident, what in changes) or 'defects: nothing to apply')
            errors = []
        elif args.command == 'record':
            if port is None and not args.no_emit:
                port = _port(setting('producer'), f'{setting("producer")}:record')
            found, outcome = record(root, args.test, args.stage, args.signature, args.base_sha, args.run, args.by,
                                    args.summary, None if args.no_emit else port)
            print(f'{found["id"]} {outcome} owner={found["owner"]} unit={found["unit"] or "-"}')
            errors = []
        else:
            if port is None and not args.no_emit:
                port = _port(setting('producer'), f'{setting("producer")}:resolve')
            found = resolve(root, args.id, args.pr, args.merge_sha, args.by, None if args.no_emit else port)
            print(f'{found["id"]} resolved')
            errors = []
    except (DefectError, forge_events.ForgeEventsError) as error:
        print(f'defects: {error}', file=sys.stderr)
        return 2
    for message in errors:
        print(message, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
