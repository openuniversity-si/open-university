"""The premise register (D-066): one record per premise, each with a blast radius (veto V0 of D-065).

A record is docs/process/premises/<slug>.yml, a strict YAML subset: `key: <JSON value>` lines and `key:` lines opening a
block indented two more spaces; full-line `#` comments. Its shape is contracts/premises/premise.v1.json and every tunable
value (radius names and rules, statuses, thresholds, the v0 switch) is read from config/registry/premises.json.

scripts/premises find|propose|answer|list|blast|check. A premise.* event is published to the repository channel of the
forge_events port (LP7, D-071: the planner reads it); `--no-emit` (dry run, no forge) prints it as `event: {...}` instead.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import config
import forge_events
import event_contracts
import json_schema

ROOT = Path(__file__).resolve().parents[2]
KEY = re.compile(r'([a-z_]+):(?: (.*))?')
HEADER = '# Premise record (D-066, contracts/premises/premise.v1.json). Change it with scripts/premises; dependents are sealed.'


class FormatError(ValueError):
    pass


def parse(text, name='record'):
    """The mapping a record's text holds; FormatError names the first line outside the subset."""
    data = {}
    stack = [(0, data)]
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        body = line.lstrip(' ')
        indent = len(line) - len(body)
        match = KEY.fullmatch(body.rstrip())
        while len(stack) > 1 and stack[-1][0] > indent:
            stack.pop()
        if not match or stack[-1][0] != indent:
            raise FormatError(f'{name}:{number}: expected "key: <JSON value>" or "key:" at indent {stack[-1][0]}')
        key, value = match.groups()
        mapping = stack[-1][1]
        if key in mapping:
            raise FormatError(f'{name}:{number}: {key} appears twice')
        if value is None:
            mapping[key] = {}
            stack.append((indent + 2, mapping[key]))
            continue
        try:
            mapping[key] = json.loads(value)
        except json.JSONDecodeError as error:
            raise FormatError(f'{name}:{number}: {key} is not a JSON value ({error.msg})') from None
    return data


def dump(record, schema):
    """The record's text, keys in the schema's order, nested objects as blocks."""
    lines = [HEADER]

    def write(mapping, properties, indent):
        order = list(properties) + sorted(key for key in mapping if key not in properties)
        for key in order:
            if key not in mapping:
                continue
            value = mapping[key]
            if isinstance(value, dict) and value:
                lines.append(f'{" " * indent}{key}:')
                write(value, properties.get(key, {}).get('properties', {}), indent + 2)
            else:
                lines.append(f'{" " * indent}{key}: {json.dumps(value, ensure_ascii=False)}')

    write(record, schema['properties'], 0)
    return '\n'.join(lines) + '\n'


_SETTINGS = {}


def setting(name):
    """A premises.* registry value, read once per process: config.get replays the store on every call, and one
    command reads the same few values hundreds of times (the unit battery is bound by battery.unit_time_limit)."""
    if name not in _SETTINGS:
        _SETTINGS[name] = config.get(f'premises.{name}')
    return _SETTINGS[name]


def register_dir(root):
    return Path(root) / setting('register_dir')


def schema(root=ROOT):
    return json.loads((Path(root) / setting('record_schema')).read_text(encoding='utf-8'))


def id_pattern():
    return f'^{setting("id_prefix")}[0-9]{{{setting("id_min_digits")},}}$'


def number(ident):
    return int(ident[len(setting('id_prefix')):])


def statuses():
    return setting('open_statuses') + setting('settled_statuses') + setting('refused_statuses')


def computed_radius(reasons, active_units=None):
    """The radius the blast reasons reach: radii[-1] for a high kind or a large enough share of the active units,
    radii[1] for a medium kind or enough units."""
    radii = setting('radii')
    kinds = [reason.partition(':')[0] for reason in reasons]
    units = kinds.count(setting('unit_reason_kind'))
    if set(kinds) & set(setting('high_reason_kinds')):
        return radii[-1]
    if active_units and units * 100 >= setting('high_blast_unit_share_percent') * active_units:
        return radii[-1]
    if set(kinds) & set(setting('medium_reason_kinds')) or units >= setting('medium_min_units'):
        return radii[min(1, len(radii) - 1)]
    return setting('default_radius')


def digest(plans, prs):
    canonical = json.dumps({'plans': sorted(plans), 'prs': sorted(prs)}, sort_keys=True, separators=(',', ':'))
    return hashlib.new(setting('digest_algorithm'), canonical.encode()).hexdigest()


def sealed(plans, prs):
    return {'plans': sorted(plans), 'prs': sorted(prs), 'digest': digest(plans, prs)}


def load(root=ROOT):
    """(records by id, errors) of the register, every record checked (D-066)."""
    root = Path(root)
    if not register_dir(root).is_dir():
        return {}, []
    shape = schema(root)
    errors = []
    if shape['properties']['id'].get('pattern') != id_pattern():
        errors.append(f'{setting("record_schema")}: the id pattern differs from premises.id_prefix and id_min_digits '
                      f'({id_pattern()}); one fact, one source')
    radii, known, by_id, slugs = setting('radii'), statuses(), {}, {}
    for path in sorted(register_dir(root).glob('*' + setting('record_suffix'))):
        name = path.relative_to(root).as_posix()
        try:
            record = parse(path.read_text(encoding='utf-8'), name)
        except FormatError as error:
            errors.append(str(error))
            continue
        problems = json_schema.errors(record, shape)
        if problems:
            errors += [f'{name}: {problem}' for problem in problems]
            continue
        problems = record_errors(record, path, radii, known)
        errors += [f'{name}: {problem}' for problem in problems]
        if record['id'] in by_id:
            errors.append(f'{name}: id {record["id"]} is also {by_id[record["id"]]["path"]}')
        if record['slug'] in slugs:
            errors.append(f'{name}: slug {record["slug"]} is also {slugs[record["slug"]]}')
        slugs[record['slug']] = name
        by_id.setdefault(record['id'], {**record, 'path': name})
    for ident, record in sorted(by_id.items()):
        errors += [f'{record["path"]}: supersedes unknown {other}' for other in record['supersedes'] if other not in by_id]
    return by_id, errors


def record_errors(record, path, radii, known):
    problems = []
    if path.name != record['slug'] + setting('record_suffix'):
        problems.append(f'the file is not named after slug {record["slug"]}')
    status, answer = record['status'], record['answer']
    if status not in known:
        problems.append(f'status {status} is not one of {known}')
    if record['radius'] not in radii:
        problems.append(f'radius {record["radius"]} is not one of {radii}')
    else:
        floor = computed_radius(record['blast']['reasons'])
        if radii.index(record['radius']) < radii.index(floor):
            problems.append(f'radius {record["radius"]} is below {floor}, computed from its blast reasons; '
                            'a radius may be raised by hand, never lowered')
    if status in setting('open_statuses'):
        if answer is not None:
            problems.append(f'status {status} has an answer; record the answer with scripts/premises answer')
    elif answer is None:
        problems.append(f'status {status} needs an answer')
    else:
        if answer['value'] != status:
            problems.append(f'answer.value {answer["value"]} is not the status {status}')
        if status in setting('quoted_statuses') and not (answer['quote'] or answer['where']):
            problems.append(f'status {status} needs a literal quote or a link to the message (answer.quote or '
                            'answer.where); a paraphrase stays inferred')
        if status in setting('measured_statuses') and not answer['evidence']:
            problems.append(f'status {status} needs the measurement in answer.evidence')
    dependents = record['dependents']
    if dependents['digest'] != digest(dependents['plans'], dependents['prs']):
        problems.append('dependents do not match their seal: they are computed by scripts/premises blast --write, '
                        'never edited by hand')
    return problems


def index_tracked(root):
    """True when the generated index is in git; it is written on demand and never committed (P-10)."""
    name = setting('index_file')
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '--', name, f'**/{name}'], capture_output=True, text=True)
    return bool(listed.stdout.strip())


def check_register(root):
    """structure-check: (errors, record count)."""
    by_id, errors = load(root)
    if index_tracked(root):
        errors.append(f'{setting("index_file")} is committed; scripts/premises list writes it on demand (P-10)')
    return errors, len(by_id)


def line_ids(text):
    """The ids of the last `Premises:` line of a body or plan, [] for `none`, None when there is no line."""
    found = re.findall(rf'^{re.escape(setting("line_name"))}:[ \t]*(.*?)[ \t]*$', text or '', re.M)
    if not found:
        return None
    tokens = [token for token in re.split(r'[,\s]+', found[-1]) if token]
    return [] if tokens == [setting('none_token')] else tokens


def words(text):
    return set(word for word in re.findall(r'[a-z0-9]+', text.lower()) if len(word) >= setting('find_min_token_length'))


def similarity(text, record):
    if text.strip().lower() in (record['slug'], record['id'].lower()):
        return 1.0
    mine, theirs = words(text), words(record['statement'] + ' ' + record['slug'].replace('-', ' '))
    if not mine or not theirs:
        return 0.0
    shared = len(mine & theirs)
    return (shared / len(mine) + shared / len(mine | theirs)) / 2  # how much of the query it covers, and how alike


def find(text, by_id):
    """The existing premises most like a statement or slug, best first (D-066: find before propose)."""
    scored = sorted(((similarity(text, record), ident) for ident, record in by_id.items()), key=lambda item: (-item[0], item[1]))
    return [(score, by_id[ident]) for score, ident in scored if score >= setting('find_min_score')][:setting('find_limit')]


def next_id(by_id):
    """v0 allocation: one past the highest id; a race between lanes fails structure-check's unique-id check (the train
    allocates at merge from v1)."""
    top = max((number(ident) for ident in by_id), default=-1)
    return setting('id_prefix') + str(top + 1).zfill(setting('id_min_digits'))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def event(kind, key, payload, at, root=ROOT):
    """The envelope of contracts/events/envelope.v1.json (M2) for a premise.* event, its payload checked against its
    schema. event_id is the idempotency key: the digest of producer, type and natural key."""
    version = setting('event_version')
    shape = json.loads((Path(root) / setting('event_schema_dir') / f'{kind}.v{version}.json').read_text(encoding='utf-8'))
    problems = json_schema.errors(payload, shape)
    if problems:
        raise ValueError(f'{kind} payload: {problems[0]}')
    producer = setting('producer')
    ident = hashlib.new(setting('digest_algorithm'), '\n'.join([producer, kind, key]).encode()).hexdigest()
    return {'event_id': ident, 'type': kind, 'version': version, 'occurred_at': at, 'producer': producer,
            'correlation_id': payload['id'], 'payload': payload}


class ForgePort:
    """Publishes premise.* envelopes to the repository channel of a forge_events adapter. The four payloads predate the
    port (no subject: forge-events.subject_exempt_schemas), so ForgeEvents.emit refuses them; this thin adapter appends
    the envelope event() already validated, idempotently by event_id. CANDIDATE (GX-37): premise.*.v2 with a subject."""

    def __init__(self, adapter=None, repo=None):
        self.adapter = adapter or forge_events.adapter_from_config()
        self.channel = forge_events.Channel(repo or config.get('forge-events.repo'), None)

    def publish(self, envelope):
        try:  # ENV-FIX-PREMISE-BLAST: an envelope outside envelope.v1 (a bad producer) never reaches the shared log
            event_contracts.registry().validate(envelope, config.get('forge-events.envelope_schema'))
        except json_schema.ValidationError as error:
            raise event_contracts.ContractError(f'{envelope["type"]}: {error}') from None
        # GATE-ON-PUSH: the newest window when the adapter has one; the repository channel (#548) is past the page cap
        recent = getattr(self.adapter, 'recent', None)
        log = recent(self.channel)[0] if recent else self.adapter.read(self.channel)
        if envelope['event_id'] not in {held.get('event_id') for held in log}:
            self.adapter.append(self.channel, [envelope])


def emit(envelope, out, port=None):
    """Publish through the port; no port (--no-emit) prints one JSON line. A forge that cannot be reached prints the
    line too, with a warning: an event is never lost to an outage."""
    if port is not None:
        try:
            return port.publish(envelope)
        except (forge_events.ForgeEventsError, OSError) as error:
            print(f'premises: {envelope["type"]} not published ({error}); printed instead', file=sys.stderr)
    print('event: ' + json.dumps(envelope, ensure_ascii=False, sort_keys=True), file=out)


def write_record(root, record):
    path = register_dir(root) / (record['slug'] + setting('record_suffix'))
    path.write_text(dump(record, schema(root)), encoding='utf-8')
    return path


def propose(root, args, out, at, port=None):
    by_id, errors = load(root)
    if errors:
        return fail(out, ['the register is invalid; run scripts/structure-check'] + errors)
    close = [(score, record) for score, record in find(args.statement, by_id) if score >= setting('duplicate_min_score')]
    close += [(1.0, record) for record in by_id.values() if record['slug'] == args.slug]
    if close:
        return fail(out, [f'{record["id"]} ({record["slug"]}) already says this (similarity {score:.2f}); cite it, or '
                          'refine it with scripts/premises answer' for score, record in close])
    reasons = list(dict.fromkeys(args.reason or []))
    radius = computed_radius(reasons, args.active_units)
    radii = setting('radii')
    if args.radius and radii.index(args.radius) > radii.index(radius):
        radius = args.radius
    opened = setting('open_statuses')
    record = {
        'id': next_id(by_id), 'slug': args.slug, 'statement': args.statement, 'kind': args.kind, 'scope': args.scope,
        'source': {'who': args.who, 'where': args.where, 'quote': args.quote, 'at': args.source_at},
        'status': opened[-1] if args.validate_how else opened[0], 'radius': radius,
        'blast': {'reasons': reasons, 'if_wrong': args.if_wrong},
        'validate': {'kind': args.validate_kind, 'how': args.validate_how},
        'answer': None, 'dependents': sealed([], []), 'supersedes': [],
    }
    problems = json_schema.errors(record, schema(root))
    if problems:
        return fail(out, problems)
    path = write_record(root, record)
    print(f'{record["id"]} {radius} {path.relative_to(root).as_posix()}', file=out)
    emit(event('premise.proposed', record['id'], {
        'id': record['id'], 'slug': record['slug'], 'statement': record['statement'], 'kind': record['kind'],
        'scope': record['scope'], 'source': {'who': args.who, 'where': args.where}, 'radius': radius,
        'reasons': reasons}, at, root), out, port)
    return 0


def answer(root, args, out, at, port=None):
    by_id, errors = load(root)
    if errors:
        return fail(out, ['the register is invalid; run scripts/structure-check'] + errors)
    if args.id not in by_id:
        return fail(out, [f'unknown premise {args.id}'])
    if args.value not in setting('settled_statuses') + setting('refused_statuses'):
        return fail(out, [f'an answer settles or refuses: {setting("settled_statuses") + setting("refused_statuses")}'])
    if args.value in setting('quote_required_statuses') and not (args.quote or '').strip():
        return fail(out, [f'{args.value} needs the literal words of the confirmation (--quote); a link or a paraphrase '
                          'stays inferred (D-069 item 10)'])
    record = {key: value for key, value in by_id[args.id].items() if key != 'path'}
    record['status'] = args.value
    record['answer'] = {'by': args.by, 'at': args.answered_at or at, 'value': args.value, 'quote': args.quote,
                        'where': args.where, 'evidence': args.evidence, 'translation': args.translation}
    path = Path(root) / by_id[args.id]['path']
    problems = json_schema.errors(record, schema(root)) + record_errors(record, path, setting('radii'), statuses())
    if problems:
        return fail(out, problems)
    write_record(root, record)
    print(f'{args.id} {args.value} by {args.by}', file=out)
    reply = record['answer']
    if args.value in setting('settled_statuses'):
        emit(event('premise.confirmed', f'{args.id}\n{args.value}\n{reply["at"]}', {
            'id': args.id, 'status': args.value, 'by': args.by, 'at': reply['at'], 'quote': args.quote,
            'where': args.where, 'evidence': args.evidence}, at, root), out, port)
    else:
        dependents = record['dependents']
        emit(event('premise.refuted', f'{args.id}\n{reply["at"]}', {
            'id': args.id, 'by': args.by, 'at': reply['at'], 'quote': args.quote, 'where': args.where,
            'dependents': {'plans': dependents['plans'], 'prs': dependents['prs']}}, at, root), out, port)
    return 0


def index_text(by_id):
    rows = ['# Premises', '', f'Generated by `scripts/premises list`; not committed (P-10). {len(by_id)} premise(s).', '',
            '| Id | Status | Radius | Statement | Answered by |', '|---|---|---|---|---|']
    for ident in sorted(by_id, key=number):
        record = by_id[ident]
        by = (record['answer'] or {}).get('by') or ''
        rows.append(f'| {ident} | {record["status"]} | {record["radius"]} | {record["statement"].replace("|", "/")} | {by} |')
    batch = [record for ident, record in sorted(by_id.items(), key=lambda item: number(item[0]))
             if record['radius'] in setting('blocking_radii') and record['status'] in setting('open_statuses')]
    rows += ['', f'## Next question batch (at most {setting("batch_max_questions")})', '']
    rows += [f'{position}. {record["id"]}: {record["validate"]["how"] or record["statement"]}'
             for position, record in enumerate(batch[:setting('batch_max_questions')], 1)] or ['None open.']
    return '\n'.join(rows) + '\n'


def plan_dependents(root, ident):
    """Tracked plan files whose `Premises:` line cites the premise."""
    from gate_areas import glob_match
    listed = subprocess.run(['git', '-C', str(root), 'ls-files'], capture_output=True, text=True).stdout.splitlines()
    found = []
    for name in listed:
        path = Path(root) / name
        if any(glob_match(name, glob) for glob in setting('plan_globs')) and path.is_file():
            if ident in (line_ids(path.read_text(encoding='utf-8', errors='replace')) or []):
                found.append(name)
    return found


def fetch_body(number):
    """A change body through the selected forge; file listing remains a separate demand."""
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'premises', f'pr-{number}', consumer='scripts/lib/premises.py')
    return port.change(config.get('forge-events.repo'), number).get('body') or ''


def blast(root, args, out, at, fetch=fetch_body, port=None):
    by_id, errors = load(root)
    if errors:
        return fail(out, ['the register is invalid; run scripts/structure-check'] + errors)
    if args.id not in by_id:
        return fail(out, [f'unknown premise {args.id}'])
    record = {key: value for key, value in by_id[args.id].items() if key != 'path'}
    recorded = record['dependents']
    plans = sorted(set(recorded['plans']) | set(plan_dependents(root, args.id)))
    prs = sorted(set(recorded['prs']) | {number for number in args.pr or [] if args.id in (line_ids(fetch(number)) or [])})
    blocking = record['radius'] in setting('blocking_radii') and record['status'] not in setting('settled_statuses')
    print(f'{args.id} radius {record["radius"]}, status {record["status"]}, {"blocks" if blocking else "does not block"} '
          f'its dependents; plans: {", ".join(plans) or "none"}; PRs: {", ".join(map(str, prs)) or "none"}', file=out)
    if args.write and (plans, prs) != (recorded['plans'], recorded['prs']):
        record['dependents'] = sealed(plans, prs)
        write_record(root, record)
    emit(event('premise.blast', f'{args.id}\n{digest(plans, prs)}', {
        'id': args.id, 'radius': record['radius'], 'reasons': record['blast']['reasons'],
        'dependents': {'plans': plans, 'prs': prs}, 'blocking': blocking}, at, root), out, port)
    return 0


def recorded(by_id, changed):
    """The premises whose record the change adds or edits: that change is the answer, so it may cite them."""
    changed = set(changed or ())
    return {ident for ident, record in by_id.items() if record['path'] in changed}


def unquoted(record):
    """True when a settled premise lacks the literal quote its status needs and is not grandfathered (D-069 item 10)."""
    answer = record.get('answer')
    if record['status'] not in setting('quote_required_statuses') or record['id'] in setting('unquoted_grandfathered'):
        return False
    return not (answer and (answer['quote'] or '').strip())


def standing(record):
    return f'{record["status"]} without a literal quote' if unquoted(record) else record['status']


def check_line(text, by_id, changed=()):
    """(errors, warnings, counted) of a body's `Premises:` line against the register (veto V0, D-066)."""
    ids = line_ids(text)
    name = setting('line_name')
    if ids is None:
        problem = (f'the body has no "{name}: P-NN, ..." (or "{name}: {setting("none_token")}") line; '
                   'run scripts/premises find (D-066)')
        return ([problem], [], 0) if setting('missing_line_fails') else ([], [problem + '; a warning in v0'], 0)
    errors, warnings, counted = [], [], 0
    pattern, own = id_pattern(), recorded(by_id, changed)
    for ident in ids:
        record = by_id.get(ident)
        if not re.fullmatch(pattern, ident):
            errors.append(f'{name}: "{ident}" is not a premise id ({pattern})')
        elif record is None:
            errors.append(f'{name}: {ident} is not in {setting("register_dir")}; propose it first')
        elif ident in own:
            counted += 1
        elif record['status'] in setting('refused_statuses'):
            errors.append(f'{name}: {ident} is {record["status"]}; the work that depends on it goes to review')
        elif record['status'] in setting('settled_statuses') and not unquoted(record):
            counted += 1
        elif record['radius'] in setting('blocking_radii'):
            errors.append(f'{name}: {ident} has radius {record["radius"]} and is {standing(record)}; it blocks this work '
                          'until it is answered with a literal quote (veto V0, D-069 item 10)')
        elif record['radius'] in setting('warning_radii'):
            warnings.append(f'{name}: {ident} has radius {record["radius"]} and is {standing(record)}')
        else:
            counted += 1
    return errors, warnings, counted


def fetch_pr(number):
    """(body, changed files) of a change through the selected forge port."""
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'premises', f'pr-{number}', consumer='scripts/lib/premises.py')
    files = [entry['filename'] for entry in port.change_files(config.get('forge-events.repo'), number)]
    return fetch_body(number), files


def check(root, args, out, fetch=fetch_pr):
    by_id, errors = load(root)
    changed = list(args.changed or [])
    if args.pr:
        try:
            text, files = fetch(args.pr)
        except (RuntimeError, forge_events.ForgeEventsError) as error:
            return fail(out, [f'PR #{args.pr} not readable ({error})'])
        changed += files
    else:
        text = args.text if args.text is not None else args.file.read_text(encoding='utf-8')
    line_errors, warnings, counted = check_line(text, by_id, changed)
    errors += line_errors
    for line in warnings:
        print('WARN ' + line, file=out)
    fail(out, errors)
    print(f'premises check: {counted} settled or low premise(s), {len(warnings)} warning(s), {len(errors)} error(s)', file=out)
    return 1 if errors else 0


def fail(out, lines):
    for line in lines:
        print('FAIL ' + line, file=out)
    return 1


def parser():
    shape = schema()
    radii = setting('radii')
    main = argparse.ArgumentParser(prog='scripts/premises', description=__doc__.splitlines()[0])
    main.add_argument('--root', type=Path, default=None, help='repository (default: this checkout)')
    main.add_argument('--at', help='RFC 3339 time of the events (default: now, UTC)')
    main.add_argument('--no-emit', action='store_true', help='dry run, no forge: print each premise.* event instead of publishing it to the forge_events repository channel')
    sub = main.add_subparsers(dest='command', required=True)
    finder = sub.add_parser('find', help='list existing premises like a statement or slug; run it before propose')
    finder.add_argument('text')
    new = sub.add_parser('propose', help='register a new premise with its computed radius')
    new.add_argument('--slug', required=True)
    new.add_argument('--statement', required=True)
    new.add_argument('--kind', required=True, choices=shape['properties']['kind']['enum'])
    new.add_argument('--scope', required=True, help='global, cell:<id> or unit:<id>')
    new.add_argument('--who', required=True, help='daniel, orchestrator, agent:<session> or model')
    new.add_argument('--where')
    new.add_argument('--quote', help="the source's literal words, if any")
    new.add_argument('--source-at', help='RFC 3339 time of the source')
    new.add_argument('--reason', action='append', help='blast reason <kind>:<target>, e.g. decision:D-065 (repeat)')
    new.add_argument('--if-wrong', required=True, help='what changes if the premise is wrong')
    new.add_argument('--radius', choices=radii, help='raise the computed radius (never lowers it)')
    new.add_argument('--active-units', type=int, help='active units, for the high-blast share (until U0 manifests exist)')
    new.add_argument('--validate-kind', required=True, choices=shape['properties']['validate']['properties']['kind']['enum'])
    new.add_argument('--validate-how', help='the question, measurement or experiment that settles it')
    reply = sub.add_parser('answer', help='record an answer with its literal quote, link or evidence')
    reply.add_argument('id')
    reply.add_argument('--value', required=True, choices=setting('settled_statuses') + setting('refused_statuses'))
    reply.add_argument('--by', required=True, help='Daniel, A Torre or measurement:<experiment>')
    reply.add_argument('--answered-at', help='RFC 3339 time of the answer (default: --at)')
    reply.add_argument('--quote')
    reply.add_argument('--where')
    reply.add_argument('--evidence')
    reply.add_argument('--translation')
    lister = sub.add_parser('list', help=f'write the index {setting("index_file")} (never committed, P-10)')
    lister.add_argument('--out', type=Path, help=f'output file (default: <root>/{setting("index_dir")}/{setting("index_file")})')
    reach = sub.add_parser('blast', help='the radius and dependents of a premise')
    reach.add_argument('id')
    reach.add_argument('--pr', type=int, action='append', help='also read this PR body over GitHub REST (repeat)')
    reach.add_argument('--write', action='store_true', help='record the dependents in the premise, sealed')
    judge = sub.add_parser('check', help='judge a Premises: line: unknown, refuted or unsettled high-radius ids fail')
    source = judge.add_mutually_exclusive_group(required=True)
    source.add_argument('--pr', type=int, help='read the PR body and its changed files over GitHub REST')
    source.add_argument('--text')
    source.add_argument('--file', type=Path)
    judge.add_argument('--changed', action='append', help='a file the change touches (repeat); its premise may be cited')
    return main


def main(argv=None, out=sys.stdout, fetch=fetch_body, fetch_pull=fetch_pr, port=None):
    args = parser().parse_args(argv)
    root = (args.root or ROOT).resolve()
    at = args.at or utc_now()
    if args.command in ('propose', 'answer', 'blast') and port is None and not args.no_emit:
        port = ForgePort()
    if args.command == 'find':
        by_id, errors = load(root)
        for score, record in find(args.text, by_id):
            print(f'{record["id"]} {score:.2f} {record["status"]} {record["radius"]} {record["slug"]}: {record["statement"]}',
                  file=out)
        return fail(out, errors) if errors else 0
    if args.command == 'propose':
        return propose(root, args, out, at, port)
    if args.command == 'answer':
        return answer(root, args, out, at, port)
    if args.command == 'list':
        by_id, errors = load(root)
        target = args.out or root / setting('index_dir') / setting('index_file')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(index_text(by_id), encoding='utf-8')
        print(f'{target}: {len(by_id)} premise(s)', file=out)
        return fail(out, errors) if errors else 0
    if args.command == 'check':
        return check(root, args, out, fetch_pull)
    return blast(root, args, out, at, fetch, port)


if __name__ == '__main__':
    sys.exit(main())
