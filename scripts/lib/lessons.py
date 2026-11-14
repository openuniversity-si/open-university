"""The lessons registry (LR1, D-069 items 4 and 9): what every unit's retro taught, kept so the engine stops repeating it.

A lesson is docs/process/lessons/<slug>.yml (strict YAML subset, shape contracts/lessons/lesson.v1.json) and its audit
trail <slug>.audit.jsonl (contracts/lessons/audit.v1.json): one line per change, only ever appended, each carrying the
digest of the one before (audit_chain). The id is a hash of (source unit, source ref, title), so reading the same retro
twice is a dedup, not a second record. Every name, suffix, status, class and transition is a lessons.* registry entry.

  add(root, ...)             a proposed lesson, or the existing one with the same key ('exists')
  apply(root, id, ...)       proposed -> applied, with the PR and the commit or file that carries the change
  retire(root, id, ...)      proposed or applied -> retired, with why
  load(root)                 (records by id, errors): schema, chain, filename, dedup, vocabularies
  check(root, base=None)     load's errors plus: no trail may lose an entry the base ref already has

scripts/lessons list|show|add|apply|retire|check|report|for-area (this module); ingestion, effect, report and the brief query are
lesson_ingest.py, lessons_effect.py, lessons_report.py and lessons_brief.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import audit_chain
import config
import forge_events
import json_schema
import premises

ROOT = Path(__file__).resolve().parents[2]
HEADER = '# Lesson record (D-069 items 4 and 9, contracts/lessons/lesson.v1.json). Change it with scripts/lessons; the trail is append-only.'
SLUG_PART = re.compile(r'[^a-z0-9]+')


class LessonError(ValueError):
    pass


def setting(name):
    return config.get(f'lessons.{name}')


def register_dir(root=ROOT):
    return Path(root) / setting('register_dir')


def _schema(name, root):
    return json.loads((Path(root) / setting(name)).read_text(encoding='utf-8'))


def normalize(text):
    return SLUG_PART.sub(' ', text.lower()).strip()


def lesson_id(unit, ref, title):
    material = f'{unit}\0{ref}\0{normalize(title)}'.encode()
    return setting('id_prefix') + hashlib.new(setting('digest_algorithm'), material).hexdigest()[:setting('id_hash_chars')]


def slug_of(unit, title, ident):
    stem = SLUG_PART.sub('-', f'{unit} {title}'.lower()).strip('-')[:setting('slug_max_chars')].strip('-')
    return f'{stem}-{ident[len(setting("id_prefix")):]}'


def paths(root, slug):
    base = register_dir(root) / slug
    return base.with_name(slug + setting('record_suffix')), base.with_name(slug + setting('audit_suffix'))


def append(trail, by, action, old, new, note, at):
    return audit_chain.append_entry(trail, by, action, old, new, note, at, setting('digest_algorithm'), setting('genesis_digest'))


def dump(record, root=ROOT):
    return premises.dump(record, _schema('record_schema', root)).replace(premises.HEADER, HEADER, 1)


def write(root, record, trail):
    record_path, trail_path = paths(root, record['slug'])
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(dump(record, root), encoding='utf-8')
    trail_path.write_text(audit_chain.dump_trail(trail), encoding='utf-8')


def vocabulary_errors(record, name):
    errors = []
    for field, key in (('class', 'classes'), ('kind', 'kinds'), ('owner', 'owners'), ('status', 'statuses')):
        if record[field] not in setting(key):
            errors.append(f'{name}: {field} {record[field]} is not one of lessons.{key}')
    if record.get('level', setting('default_level')) not in setting('levels'):
        errors.append(f'{name}: level {record["level"]} is not one of lessons.levels')
    return errors


def load(root=ROOT):
    """(records by id, errors). Every record carries its trail under 'trail' in memory only."""
    root = Path(root)
    found, errors, keys = {}, [], {}
    if not register_dir(root).is_dir():
        return found, errors
    shape, audit = _schema('record_schema', root), _schema('audit_schema', root)
    suffix = setting('record_suffix')
    for path in sorted(register_dir(root).glob('*' + suffix)):
        name = path.relative_to(root).as_posix()
        try:
            record = premises.parse(path.read_text(encoding='utf-8'), name)
            trail = audit_chain.read_trail(path.with_name(path.name[:-len(suffix)] + setting('audit_suffix')))
        except (premises.FormatError, ValueError) as error:
            errors.append(str(error))
            continue
        problems = [f'{name}: {message}' for message in json_schema.errors(record, shape)]
        for number, entry in enumerate(trail, 1):
            problems += [f'{name} trail {number}: {message}' for message in json_schema.errors(entry, audit)]
        if problems:
            errors += problems
            continue
        errors += audit_chain.chain_errors(trail, name, setting('digest_algorithm'), setting('genesis_digest'))
        source = record['source']
        if record['id'] != lesson_id(source['unit'], source['ref'], record['title']):
            errors.append(f'{name}: id {record["id"]} is not the hash of its source unit, ref and title')
        if path.stem != slug_of(source['unit'], record['title'], record['id']) or record['slug'] != path.stem:
            errors.append(f'{name}: the file name must be {slug_of(source["unit"], record["title"], record["id"])}')
        errors += vocabulary_errors(record, name)
        if not trail or trail[-1]['to'] != record['status']:
            errors.append(f'{name}: the last trail entry must end in the record status {record["status"]}')
        if (record['status'] == 'applied' and not record['applied']) or (record['status'] == 'proposed' and record['applied']):
            errors.append(f'{name}: an applied lesson carries the applied block and a proposed one does not')
        if record['id'] in found:
            errors.append(f'{name}: duplicates {found[record["id"]]["slug"]}')
        record['trail'] = trail
        found[record['id']] = record
        keys[record['id']] = name
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


def now_text(moment):
    return forge_events.rfc3339(moment)


def emit(port, kind, record, root, extra):
    """Publish a lesson event through the forge_events port; no port, no event (--no-emit, tests)."""
    if port is None:
        return None
    subject = forge_events.subject(config.get('forge-events.repo'), None, None, (), None)
    base = {'lesson': record['id'], 'class': record['class']}
    return port.emit(kind, dict(subject, **base, **extra))


def _port(correlation):
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    setting('producer'), f'{setting("producer")}:{correlation}')


def _loaded(root):
    records, errors = load(root)
    if errors:
        raise LessonError('; '.join(errors))
    return records


def add(root, title, unit, retro, section, ref, cls, kind, change, owner, area=(), signals=(), by=None, clock=None, port=None, level=None, padrao_candidate=False):
    """(record, 'created' | 'exists'). The same (unit, ref, title) is the same lesson."""
    ident = lesson_id(unit, ref, title)
    existing = _loaded(root)
    if ident in existing:
        return existing[ident], 'exists'
    new = {'id': ident, 'slug': slug_of(unit, title, ident), 'title': title,
           'source': {'unit': unit, 'retro': retro, 'section': section, 'ref': ref},
           'class': cls, 'kind': kind, 'change': change, 'owner': owner, 'status': setting('statuses')[0],
           'area': list(area), 'signals': list(signals), 'applied': None, 'effect': None,
           'level': level or setting('default_level'), 'padrao_candidate': bool(padrao_candidate)}
    problems = [f'{field} {new[field]} is not one of lessons.{key}'
                for field, key in (('class', 'classes'), ('kind', 'kinds'), ('owner', 'owners')) if new[field] not in setting(key)]
    if new['level'] not in setting('levels'):
        problems.append(f'level {new["level"]} is not one of lessons.levels')
    problems += [f'{message}' for message in json_schema.errors(new, _schema('record_schema', root))]
    if problems:
        raise LessonError('; '.join(problems))
    trail = append([], by or setting('by_default'), 'registered', None, new['status'], f'{retro} section {section} {ref}', now(clock))
    write(root, new, trail)
    emit(port, 'lesson.recorded', new, root, {'kind': kind, 'owner': owner, 'source_unit': unit})
    return dict(new, trail=trail), 'created'


def transition(root, ident, to, by, action, note, applied=None, clock=None, port=None, extra=None):
    records = _loaded(root)
    if ident not in records:
        raise LessonError(f'unknown lesson {ident}')
    current = records[ident]
    trail = current.pop('trail')
    if f'{current["status"]}>{to}' not in setting('transitions'):
        raise LessonError(f'{ident}: {current["status"]} cannot become {to} (lessons.transitions)')
    stamp = now(clock)
    trail = append(trail, by or setting('by_default'), action, current['status'], to, note, stamp)
    current['status'] = to
    if applied is not None:
        current['applied'] = dict(applied, at=stamp)
    write(root, current, trail)
    current['trail'] = trail
    if port is not None and action in ('applied', 'retired'):
        owned = {'kind': current['kind'], 'owner': current['owner']} if action == 'applied' else {}
        emit(port, f'lesson.{action}', current, root, dict(owned, **(extra or {})))
    return current


def record_effect(root, ident, effect, by=None, clock=None):
    """Store a measured effect (status unchanged); the trail names the numbers."""
    records = _loaded(root)
    if ident not in records:
        raise LessonError(f'unknown lesson {ident}')
    current = records[ident]
    trail = current.pop('trail')
    note = f'{effect["verdict"]}: {effect["before"]} before, {effect["after"]} after, {effect["window_days"]} d window'
    trail = append(trail, by or setting('by_default'), 'measured', current['status'], current['status'], note, effect['measured_at'])
    current['effect'] = effect
    write(root, current, trail)
    current['trail'] = trail
    return current


def apply(root, ident, pr, ref, by=None, clock=None, port=None):
    """proposed -> applied: the change is in the engine (a merged PR, a commit, a file)."""
    return transition(root, ident, 'applied', by, 'applied', f'applied by PR #{pr}: {ref}' if pr else f'applied: {ref}',
                      applied={'pr': pr, 'ref': ref}, clock=clock, port=port, extra={'applied_pr': pr, 'ref': ref})


def apply_lesson(root, ident, decision, by=None, clock=None, port=None):
    """The planner's path (D-071): a plan decision applies a lesson, no PR needed. (record, 'applied' | 'already').
    Same audit line and lesson.applied as apply(); an applied lesson is a no-op, a retired one is refused by name."""
    records = _loaded(root)
    if ident not in records:
        raise LessonError(f'unknown lesson {ident}')
    if records[ident]['status'] == setting('statuses')[1]:
        return records[ident], 'already'
    return apply(root, ident, None, decision, by, clock=clock, port=port), 'applied'


def retire(root, ident, why, by=None, clock=None, port=None):
    return transition(root, ident, 'retired', by, 'retired', why, clock=clock, port=port, extra={'why': why})


def render(records, columns=None):
    columns = columns or setting('list_columns')
    rows = [[str(record.get('source', {}).get('unit') if column == 'unit' else record.get(column) or '-') for column in columns]
            for record in sorted(records.values(), key=lambda r: r['id'])]
    widths = [max(len(column), *(len(row[i]) for row in rows)) if rows else len(column) for i, column in enumerate(columns)]
    lines = ['  '.join(column.ljust(widths[i]) for i, column in enumerate(columns))]
    return lines + ['  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]


def show(record):
    lines = [f'{key}: {json.dumps(record[key], ensure_ascii=False)}' for key in record if key != 'trail']
    return lines + [f'trail {entry["n"]}: {entry["at"]} {entry["by"]} {entry["action"]} {entry["from"]}>{entry["to"]} {entry["note"]}'
                    for entry in record['trail']]


def parser_for(root):
    parser = argparse.ArgumentParser(prog='scripts/lessons', description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=str(root))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    shown = sub.add_parser('show'); shown.add_argument('id')
    new = sub.add_parser('add')
    for flag in ('title', 'source-unit', 'source-retro', 'ref', 'class', 'kind', 'change', 'owner'):
        new.add_argument('--' + flag, required=True)
    new.add_argument('--section', type=int, required=True)
    new.add_argument('--level'); new.add_argument('--padrao-candidate', action='store_true')
    new.add_argument('--area', action='append', default=[]); new.add_argument('--by'); new.add_argument('--no-emit', action='store_true')
    done = sub.add_parser('apply')
    done.add_argument('id'); done.add_argument('--ref', required=True); done.add_argument('--pr', type=int); done.add_argument('--by'); done.add_argument('--no-emit', action='store_true')
    gone = sub.add_parser('retire')
    gone.add_argument('id'); gone.add_argument('--why', required=True); gone.add_argument('--by'); gone.add_argument('--no-emit', action='store_true')
    chk = sub.add_parser('check'); chk.add_argument('--base')
    ing = sub.add_parser('ingest')
    ing.add_argument('--retro', action='append', default=[], help='retro file to read (default: every lessons.ingest_glob)')
    ing.add_argument('--pr', type=int, help='read the RETRO comment of this PR'); ing.add_argument('--unit', help='unit of the PR retro')
    ing.add_argument('--no-emit', action='store_true')
    eff = sub.add_parser('effect')
    eff.add_argument('id', nargs='?'); eff.add_argument('--events-file', help='JSON Lines of event envelopes (offline log)')
    eff.add_argument('--pr', type=int, action='append', default=[], help='also read the log of this PR channel')
    eff.add_argument('--write', action='store_true', help='store the measured effect in the record and its trail')
    rep = sub.add_parser('report')
    rep.add_argument('--events-file', help='JSON Lines of event envelopes; without it the report is built from the registry alone')
    rep.add_argument('--pr', type=int, action='append', default=[], help='also read the log of this PR channel')
    rep.add_argument('--live', action='store_true', help='read the repository event log')
    rep.add_argument('--write', action='store_true', help='write lessons.report_path')
    rep.add_argument('--check', action='store_true', help='exit 1 when lessons.report_path differs from the regenerated report')
    rep.add_argument('--no-emit', action='store_true')
    area = sub.add_parser('for-area')
    area.add_argument('paths', nargs='+'); area.add_argument('--json', action='store_true')
    return parser


def effect_events(args, port):
    """The event log the effect is counted over: the repository channel, the PR channels given, and an offline file."""
    events = []
    if args.events_file:
        events += [json.loads(line) for line in Path(args.events_file).read_text(encoding='utf-8').splitlines() if line.strip()]
    else:
        port = port or _port('effect')
        repo = config.get('forge-events.repo')
        for pr in [None, *args.pr]:
            events += port.read(repo, pr)
    return events


def main(argv=None, root=ROOT, port=None):
    args = parser_for(root).parse_args(argv)
    root = Path(args.root)
    errors = []
    try:
        if args.command == 'list':
            print('\n'.join(render(_loaded(root))))
        elif args.command == 'show':
            records = _loaded(root)
            if args.id not in records:
                raise LessonError(f'unknown lesson {args.id}')
            print('\n'.join(show(records[args.id])))
        elif args.command == 'check':
            records, errors = check(root, args.base)
            print(f'lessons: {len(records)} record(s), {len(errors)} error(s)')
        elif args.command == 'ingest':
            import lesson_ingest  # imports this module; loaded only for this command
            if args.pr:
                if not args.unit:
                    raise LessonError('--pr needs --unit')
                text = lesson_ingest.comment_text((port or _port('ingest')).comments(config.get('forge-events.repo'), args.pr))
                if text is None:
                    raise LessonError(f'PR #{args.pr} has no comment titled {setting("retro_comment_title")}')
                found = lesson_ingest.parse(text, args.unit, f'pr-comment:{args.pr}')
            else:
                found = lesson_ingest.candidates_of_files(root, [Path(name) for name in args.retro] or None)
            outcomes = lesson_ingest.ingest(root, found, port=None if args.no_emit else port or _port('ingest'))
            print('\n'.join(f'{ident} {what}' for ident, what in outcomes) or 'lessons: no retro to read')
        elif args.command == 'effect':
            import lessons_effect  # imports this module; loaded only for this command
            records = _loaded(root)
            events = effect_events(args, port)
            moment = forge_events.clock_from_config().now()
            for ident in [args.id] if args.id else sorted(records):
                if ident not in records:
                    raise LessonError(f'unknown lesson {ident}')
                result = lessons_effect.measure(records[ident], events, moment)
                if result is None:
                    continue
                print(f'{ident} {result["verdict"]}: {result["before"]} before, {result["after"]} after ({result["window_days"]} d)')
                if args.write:
                    record_effect(root, ident, result)
        elif args.command == 'report':
            import lessons_report  # imports this module; loaded only for this command
            records = _loaded(root)
            use_log = args.live or args.events_file or args.pr
            events = effect_events(args, port) if use_log else []
            text = lessons_report.render(records, events, f'{len(events)} event(s)' if use_log else 'not read (registry only)')
            target = root / setting('report_path')
            if args.check:
                if not target.is_file() or target.read_text(encoding='utf-8') != text:
                    errors.append(f'{setting("report_path")} differs from its regeneration; run scripts/lessons report --write')
            elif args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
                lessons_report.publish(None if args.no_emit else port or _port('report'), records, events, text)
                print(f'{setting("report_path")} {lessons_report.digest(text)}')
            else:
                print(text, end='')
        elif args.command == 'for-area':
            import lessons_brief  # imports this module; loaded only for this command
            found = lessons_brief.for_area(_loaded(root), args.paths)
            if args.json:
                print(json.dumps([{key: record[key] for key in ('id', 'kind', 'change', 'owner', 'area')} for record in found], indent=2))
            else:
                print('\n'.join(lessons_brief.render(found)) or 'lessons: none applied for this area')
        elif args.command == 'add':
            found, outcome = add(root, args.title, args.source_unit, args.source_retro, args.section, args.ref, getattr(args, 'class'),
                                 args.kind, args.change, args.owner, args.area, (), args.by,
                                 port=None if args.no_emit else port or _port('add'),
                                 level=args.level, padrao_candidate=args.padrao_candidate)
            print(f'{found["id"]} {outcome}')
        elif args.command == 'apply':
            print(f'{apply(root, args.id, args.pr, args.ref, args.by, port=None if args.no_emit else port or _port("apply"))["id"]} applied')
        else:
            print(f'{retire(root, args.id, args.why, args.by, port=None if args.no_emit else port or _port("retire"))["id"]} retired')
    except (LessonError, KeyError, forge_events.ForgeEventsError) as error:
        print(f'lessons: {error}', file=sys.stderr)
        return 2
    for message in errors:
        print(message, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
