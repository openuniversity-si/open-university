"""The rule register (RULE-AUDIT rule system; Daniel 2026-10-28 16:52, 16:55, 17:08 and 17:09 BRT; D-069 item 9, D-072).

Every rule that can stop a flow (refuse, fail a gate, block a merge) is a record of the registry parameter
rules.catalog (config/registry/rules.json): what it requires, where it is implemented, its owner, when and by whom it
was created, its review date, its end condition, whether it stops, the damage if what it stops gets through, the
impact of removing it, the premises it rests on (P-NN of the premise register, read through scripts/lib/premises.py,
never beside it), its standing question with the answers it got, and for a rule that stops, its stop record (how many
times it stopped the flow, where that was read, the root cause and the cheapest fix). The registry checks a record's
shape; this module counts what the shape cannot say:

  record_gaps(record, world)  the missing or invalid fields of one record (a stopping record needs every field)
  due(world)                  active records whose review_by has passed
  ending(world)               active records whose end condition holds, or whose code is gone: proposed retirements,
                              each with the exact registry change (the retiring decision is left for a person to name)
  unregistered(world)         stopping functions rules.stop_patterns finds that no active record lists in `where`:
                              stops without a question
  accidents(world)            stopping records never measured, or that stopped the flow with no root cause named
  unanswered(world)           active records whose standing question has no answer
  premise_findings(world)     active records citing no premise, or a refuted, unsettled or undated one
  stale(world)                every refuted, unsettled or undated premise with the rules that cite it
  refusals(report)            what refuse mode would refuse; report mode (rules.check_mode) refuses nothing
  check(world, mode, base)    the whole report with its counts

The functions take a World (records, settings, premises, decisions, `today`, `root`), so a test injects each value;
load(root, today) reads them from local files only. main() pins the configuration store to the checkout's local log,
so no value is read from the forge: the rule system makes no network call. The one write is `question --answer`,
which appends an answer to rules.json in the checkout.

scripts/rule list | show <id> | due | retired | stale | question <id|group> [--answer TEXT --by WHO [--on DATE]]
| check [--mode report|refuse] [--base REF] [--json]; every subcommand takes --root DIR and --today YYYY-MM-DD and
ends with a count line. A usage error exits through argparse.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import config
import premises

ROOT = Path(__file__).resolve().parent.parent.parent
OWNER = 'rules'
NAMES = ('catalog', 'check_mode', 'max_review_days', 'stop_patterns', 'decision_register', 'census_file', 'groups_file')
DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
DECISION = re.compile(r'D-[0-9]{3}')
DECISION_ROW = re.compile(r'^\| (D-[0-9]{3}) \|', re.M)
PERSON = re.compile(r'(?P<who>\S.*?) (?P<on>[0-9]{4}-[0-9]{2}-[0-9]{2})')
REF = re.compile(r'(?P<path>[^:#\s]+)(?::(?P<name>[A-Za-z_][A-Za-z0-9_]*)|#(?P<key>\S+))?')
INDENT = re.compile(r'^( +)\S', re.M)
REQUIRED = ('id', 'statement', 'where', 'owner', 'created', 'review_by', 'ends_when', 'stops', 'premises', 'question',
            'status')
STOPPING = ('damage_if_passed', 'impact_of_removal')
IMPACT = ('positive', 'negative', 'measured')
END_FIELDS = {'manual': (), 'date': ('on',), 'path_exists': ('path',), 'path_absent': ('path',),
              'registry_equals': ('key', 'equals')}
GROUP_ROWS = ('rows', 'row_ids', 'members', 'ids')
CENSUS_FIELDS = ('kind', 'where', 'what', 'owner', 'fired', 'stops_flow')
ACTIVE, RETIRED = 'active', 'retired'
REPORT, REFUSE = 'report', 'refuse'
PENDING_DECISION = '<D-NNN required>'


def setting(name, root=None):
    return config.get(f'{OWNER}.{name}', root)


def settings(root=None):
    """{name: value} of every rules.* parameter of the checkout at `root`."""
    return {name: setting(name, root) for name in NAMES}


def registry_file(root):
    """The checkout-relative path of the rules registry file."""
    found = config.files(root).get(OWNER)
    return found[0].relative_to(root).as_posix() if found else None


def date_of(value):
    """The date a YYYY-MM-DD string names; None for anything else, a calendar date that does not exist included."""
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def decisions(root, register):
    """The D-NNN ids recorded as table rows of the decision register."""
    path = Path(root) / register
    return set(DECISION_ROW.findall(path.read_text(encoding='utf-8'))) if path.is_file() else set()


class World:
    """Everything the checks read: the records, the rules.* settings, the premise register (by id), the recorded
    decisions, today and the checkout. value_of(name) answers a registry_equals end condition."""

    def __init__(self, root, today, values, by_id, recorded, value_of=None, premise_errors=(), registry=None):
        self.root = Path(root)
        self.today = today
        self.settings = values
        self.records = [record for record in values['catalog'] if isinstance(record, dict)]
        self.premises = by_id
        self.decisions = set(recorded)
        self.value_of = value_of or (lambda name: config.get(name, self.root))
        self.premise_errors = list(premise_errors)
        self.registry = registry or f'config/registry/{OWNER}.json'
        self.unsettled = set(premises.setting('open_statuses'))
        self.refused = set(premises.setting('refused_statuses'))


def load(root=ROOT, today=None):
    """The World of a checkout, read from local files: its registry, premise register and decision register."""
    root = Path(root)
    values = settings(root)
    by_id, premise_errors = premises.load(root)
    recorded = decisions(root, values['decision_register'])
    return World(root, today or utc_today(), values, by_id, recorded, premise_errors=premise_errors,
                 registry=registry_file(root))


def utc_today():
    return datetime.now(timezone.utc).date()


def is_active(record):
    return record.get('status', ACTIVE) != RETIRED


def is_stopping(record):
    """A record stops unless it says it does not: a missing `stops` is judged as the strictest case."""
    return record.get('stops') is not False


def active(world):
    return [record for record in world.records if is_active(record)]


def text_missing(value):
    return not isinstance(value, str) or not value.strip()


def ref_state(root, ref):
    """'ok', 'gone' (the file, function or key no longer exists) or 'malformed' for one `where` ref."""
    match = REF.fullmatch(ref) if isinstance(ref, str) else None
    if not match or match['path'].startswith('/') or '..' in Path(match['path']).parts:
        return 'malformed'
    target = Path(root) / match['path']
    if not target.is_file():
        return 'gone'
    if not (match['name'] or match['key']):
        return 'ok'
    text = target.read_text(encoding='utf-8', errors='replace')
    if match['name']:
        name = re.escape(match['name'])
        if target.suffix == '.py':
            found = re.search(rf'^\s*(?:async\s+)?(?:def|class)\s+{name}\b', text, re.M)
        else:
            found = re.search(rf'(?<![\w-]){name}(?![\w-])', text)
        return 'ok' if found else 'gone'
    if target.suffix == '.json':
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            return 'gone'
        if not isinstance(document, dict):
            return 'gone'
        return 'ok' if match['key'] in (document.get('properties') or {}) or match['key'] in document else 'gone'
    return 'ok' if match['key'] in text else 'gone'


def gone_refs(record, world):
    where = record.get('where')
    return [ref for ref in where if ref_state(world.root, ref) == 'gone'] if isinstance(where, list) else []


def owner_gaps(owner, world):
    if text_missing(owner):
        return ['owner is empty']
    if DECISION.fullmatch(owner):
        return [] if owner in world.decisions else [f'owner {owner} is not a row of {world.settings["decision_register"]}']
    match = PERSON.fullmatch(owner)
    if not match or date_of(match['on']) is None:
        return [f'owner {owner!r} is neither a recorded D-NNN nor "<name> YYYY-MM-DD"']
    return []


def date_gaps(record, world):
    """created {on, by}, last_reviewed and review_by: real dates in order, review_by at most rules.max_review_days
    after the later of created.on and last_reviewed. A review_by already passed is not a gap: due() counts it."""
    gaps, created_on, reviewed = [], None, None
    created = record.get('created')
    if 'created' in record and not isinstance(created, dict):
        gaps.append('created is not {on, by}')
    elif isinstance(created, dict):
        created_on = date_of(created.get('on'))
        if created_on is None:
            gaps.append(f'created.on {created.get("on")!r} is not a real YYYY-MM-DD date')
        elif created_on > world.today:
            gaps.append(f'created.on {created_on} is after today ({world.today})')
        if text_missing(created.get('by')):
            gaps.append('created.by is missing')
    if 'last_reviewed' in record:
        reviewed = date_of(record['last_reviewed'])
        if reviewed is None:
            gaps.append(f'last_reviewed {record["last_reviewed"]!r} is not a real YYYY-MM-DD date')
        elif reviewed > world.today or (created_on and reviewed < created_on):
            gaps.append(f'last_reviewed {reviewed} is not between created.on and today')
            reviewed = None
    if 'review_by' not in record:
        return gaps
    review = date_of(record['review_by'])
    if review is None:
        return gaps + [f'review_by {record["review_by"]!r} is not a real YYYY-MM-DD date']
    if created_on and review <= created_on:
        gaps.append(f'review_by {review} is not after created.on {created_on}')
    start = max((day for day in (created_on, reviewed) if day), default=None)
    limit = world.settings['max_review_days']
    if start and review > start + timedelta(days=limit):
        gaps.append(f'review_by {review} is more than rules.max_review_days ({limit}) after {start}')
    return gaps


def end_gaps(end, world):
    if not isinstance(end, dict):
        return ['ends_when is not an object']
    kind = end.get('kind')
    if kind not in END_FIELDS:
        return [f'ends_when.kind {kind!r} is not one of {", ".join(END_FIELDS)}']
    gaps = ['ends_when.text is missing'] if text_missing(end.get('text')) else []
    gaps += [f'ends_when {kind} needs {field}' for field in END_FIELDS[kind] if field not in end]
    if kind == 'date' and 'on' in end and date_of(end['on']) is None:
        gaps.append(f'ends_when.on {end["on"]!r} is not a real YYYY-MM-DD date')
    if kind in ('path_exists', 'path_absent') and 'path' in end and ref_state(world.root, end['path']) == 'malformed':
        gaps.append(f'ends_when.path {end["path"]!r} is not a repository-relative path')
    if kind == 'registry_equals' and 'key' in end:
        try:
            world.value_of(end['key'])
        except (config.ConfigError, TypeError):
            gaps.append(f'ends_when.key {end["key"]!r} is not a registered parameter')
    return gaps


def answer_gaps(answer, world):
    if not isinstance(answer, dict):
        return ['an answer is not {on, by, text}']
    gaps = [f'question.answers: {field} is missing' for field in ('by', 'text') if text_missing(answer.get(field))]
    on = date_of(answer.get('on'))
    if on is None or on > world.today:
        gaps.append(f'question.answers: on {answer.get("on")!r} is not a real date up to today')
    return gaps


def question_gaps(question, world):
    """A question needs its text; an answer needs on, by and text. No answer yet is a finding, not a gap."""
    if not isinstance(question, dict):
        return ['question is not {text, answers}']
    gaps = ['question.text is missing'] if text_missing(question.get('text')) else []
    answers = question.get('answers', [])
    if not isinstance(answers, list):
        return gaps + ['question.answers is not a list']
    return gaps + [gap for answer in answers for gap in answer_gaps(answer, world)]


def stop_record_gaps(stop, world):
    """A stop record: count (a whole number, or null when never measured), source, measured_on when counted,
    root_cause and cheapest_fix (text or null). A missing record is a finding of accidents(), not a gap."""
    if not isinstance(stop, dict):
        return ['stop_record is not an object']
    gaps = ['stop_record.source is missing'] if text_missing(stop.get('source')) else []
    count = stop.get('count')
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        gaps.append(f'stop_record.count {count!r} is not a whole number or null')
    elif count is not None:
        on = date_of(stop.get('measured_on'))
        if on is None or on > world.today:
            gaps.append(f'stop_record.measured_on {stop.get("measured_on")!r} is not a real date up to today')
    for field in ('root_cause', 'cheapest_fix'):
        if stop.get(field) is not None and not isinstance(stop.get(field), str):
            gaps.append(f'stop_record.{field} is not text or null')
    return gaps


def retirement_gaps(record, world):
    retired = record.get('retired')
    if not isinstance(retired, dict):
        return ['retired {on, by, reason} is missing: a retirement names its decision']
    gaps = []
    if date_of(retired.get('on')) is None:
        gaps.append(f'retired.on {retired.get("on")!r} is not a real YYYY-MM-DD date')
    by = retired.get('by')
    if not (isinstance(by, str) and DECISION.fullmatch(by)):
        gaps.append(f'retired.by {by!r} is not a D-NNN')
    elif by not in world.decisions:
        gaps.append(f'retired.by {by} is not a row of {world.settings["decision_register"]}')
    if text_missing(retired.get('reason')):
        gaps.append('retired.reason is missing')
    return gaps


def record_gaps(record, world):
    """The missing or invalid fields of one record. Every record needs id, statement, where, owner, created,
    review_by, ends_when, stops, premises, question and status; a stopping one also damage_if_passed and
    impact_of_removal. A retired record is judged on its retirement only. Unknown premise ids are gaps; an empty premise
    list, an unanswered question and a missing stop record are findings, not gaps."""
    if record.get('status') == RETIRED:
        return retirement_gaps(record, world)
    gaps = [f'{field} is missing' for field in REQUIRED if field not in record]
    if 'status' in record and record['status'] != ACTIVE:
        gaps.append(f'status {record["status"]!r} is not {ACTIVE} or {RETIRED}')
    if 'retired' in record:
        gaps.append('retired is set on an active record')
    if 'statement' in record and text_missing(record['statement']):
        gaps.append('statement is empty')
    where = record.get('where')
    if 'where' in record:
        if not isinstance(where, list) or not where:
            gaps.append('where names no ref (path:function or path#key)')
        else:
            gaps += [f'where ref {ref!r} is not path, path:function or path#key' for ref in where
                     if ref_state(world.root, ref) == 'malformed']
            gone = gone_refs(record, world)
            if gone and len(gone) < len(where):
                gaps += [f'where ref {ref} no longer exists (moved? update where)' for ref in gone]
    if 'owner' in record:
        gaps += owner_gaps(record['owner'], world)
    gaps += date_gaps(record, world)
    if 'ends_when' in record:
        gaps += end_gaps(record['ends_when'], world)
    if 'stops' in record and not isinstance(record['stops'], bool):
        gaps.append('stops is not true or false')
    cited = record.get('premises')
    if 'premises' in record and not isinstance(cited, list):
        gaps.append('premises is not a list of P-NN')
    elif isinstance(cited, list):
        gaps += [f'premise {ident} is not in the premise register' for ident in cited if ident not in world.premises]
    if 'question' in record:
        gaps += question_gaps(record['question'], world)
    if 'stop_record' in record:
        gaps += stop_record_gaps(record['stop_record'], world)
    if is_stopping(record):
        gaps += [f'{field} is missing (the record stops)' for field in STOPPING if field not in record]
        if 'damage_if_passed' in record and text_missing(record['damage_if_passed']):
            gaps.append('damage_if_passed is empty')
        if 'impact_of_removal' in record:
            impact = record['impact_of_removal'] if isinstance(record['impact_of_removal'], dict) else {}
            gaps += [f'impact_of_removal.{part} is missing' for part in IMPACT if text_missing(impact.get(part))]
    return gaps


def due(world):
    """[(record, days overdue)] of the active records whose review_by has passed."""
    found = []
    for record in active(world):
        review = date_of(record.get('review_by'))
        if review and review < world.today:
            found.append((record, (world.today - review).days))
    return found


def answers(record):
    question = record.get('question')
    found = question.get('answers') if isinstance(question, dict) else None
    return [answer for answer in found if isinstance(answer, dict)] if isinstance(found, list) else []


def latest_answer(record):
    """The answer with the latest date (the last one written on a tie), else None."""
    found = list(enumerate(answers(record)))
    return max(found, key=lambda item: (str(item[1].get('on')), item[0]))[1] if found else None


def unanswered(world):
    """The active records whose standing question has no answer (or no question at all)."""
    return [record for record in active(world) if not answers(record)]


def accidents(world):
    """Rows {id, finding} of every active stopping record that was never measured (no stop record, or a null count)
    or that stopped the flow with no root cause named: every stop of the flow is an accident with a cause (17:08)."""
    rows = []
    for record in active(world):
        if not is_stopping(record):
            continue
        stop = record.get('stop_record')
        count = stop.get('count') if isinstance(stop, dict) else None
        if count is None:
            rows.append({'id': record.get('id'), 'finding': 'stops the flow and has never been measured '
                         + ('(no stop_record)' if not isinstance(stop, dict) else '(stop_record.count is null)')})
        elif isinstance(count, int) and count > 0 and text_missing(stop.get('root_cause')):
            rows.append({'id': record.get('id'), 'finding': f'stopped the flow {count} time(s) ({stop.get("source")}, '
                         f'{stop.get("measured_on")}) and no root cause is named'})
    return rows


def end_reached(record, world):
    """The reason the record's end condition holds today, else None; a manual end never holds by itself."""
    end = record.get('ends_when')
    if not isinstance(end, dict):
        return None
    kind = end.get('kind')
    if kind == 'date':
        on = date_of(end.get('on'))
        return f'ends_when date {on} reached' if on and on <= world.today else None
    if kind in ('path_exists', 'path_absent') and isinstance(end.get('path'), str):
        if ref_state(world.root, end['path']) == 'malformed':
            return None
        exists = (world.root / end['path']).exists()
        return f'ends_when {kind} {end["path"]} holds' if exists == (kind == 'path_exists') else None
    if kind == 'registry_equals' and 'key' in end and 'equals' in end:
        try:
            value = world.value_of(end['key'])
        except (config.ConfigError, TypeError):
            return None
        return f'ends_when {end["key"]} equals {json.dumps(end["equals"])}' if value == end['equals'] else None
    return None


def proposal(record, reason, world):
    """A proposed retirement with the exact registry change; a person names the retiring decision."""
    change = {'status': RETIRED, 'retired': {'on': world.today.isoformat(), 'by': PENDING_DECISION, 'reason': reason}}
    return {'id': record.get('id'), 'reason': reason, 'change': change}


def ending(world):
    """Proposed retirements: active records whose end condition holds, or whose every `where` ref is gone."""
    found = []
    for record in active(world):
        reason = end_reached(record, world)
        where = record.get('where')
        gone = gone_refs(record, world)
        if not reason and isinstance(where, list) and where and len(gone) == len(where):
            reason = 'code gone: ' + ', '.join(gone) + ' no longer exist'
        if reason:
            found.append(proposal(record, reason, world))
    return found


def discovered(root, patterns):
    """Every <file>:<function> the stop patterns match, sorted (a function defined twice in one file counts once)."""
    found = set()
    for item in patterns:
        regex = re.compile(item['regex'])
        for path in sorted(Path(root).glob(item['glob'])):
            if not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                match = regex.search(line)
                if match:
                    found.add(f'{name}:{match.group(1) if regex.groups else match.group(0)}')
    return sorted(found)


def unregistered(world, found=None):
    """The stopping functions rules.stop_patterns finds that no active record lists in `where`: each is a stop without
    a question, since it has no record and so no question."""
    found = discovered(world.root, world.settings['stop_patterns']) if found is None else found
    known = {ref for record in active(world) for ref in (record.get('where') or []) if isinstance(ref, str)}
    return [ref for ref in found if ref not in known]


def premise_date(premise):
    """The date of a premise's current status: its answer's for an answered premise, else its source's."""
    answer = premise.get('answer')
    return answer.get('at') if isinstance(answer, dict) else (premise.get('source') or {}).get('at')


def stale_label(premise, world):
    """Why citing the premise is unsafe, else None: refuted or superseded (premises.refused_statuses), unsettled
    (premises.open_statuses: inferred, to-validate), or no date on its current status (`at` null)."""
    status = premise.get('status')
    unsafe = status in world.refused or status in world.unsettled
    if premise_date(premise):
        return status if unsafe else None
    return f'{status}, undated'


def premise_findings(world):
    """Rows {id, stops, premise, finding} for every active record that cites no premise or a stale one."""
    rows = []
    for record in active(world):
        cited = record.get('premises')
        if isinstance(cited, list) and not cited:
            rows.append({'id': record.get('id'), 'stops': is_stopping(record), 'premise': None, 'finding': 'cites no premise'})
        for ident in cited if isinstance(cited, list) else []:
            label = stale_label(world.premises[ident], world) if ident in world.premises else None
            if label:
                rows.append({'id': record.get('id'), 'stops': is_stopping(record), 'premise': ident, 'finding': label})
    return rows


def stale(world):
    """Every refuted, unsettled or undated premise of the register with the active records that cite it."""
    citing = defaultdict(list)
    for record in active(world):
        for ident in record.get('premises') if isinstance(record.get('premises'), list) else []:
            citing[ident].append(record)
    rows = []
    for ident in sorted(world.premises, key=premises.number):
        premise = world.premises[ident]
        label = stale_label(premise, world)
        if label:
            rules = citing.get(ident, [])
            rows.append({'premise': ident, 'label': label, 'radius': premise.get('radius'),
                         'statement': premise.get('statement'), 'rules': [record.get('id') for record in rules],
                         'stopping': [record.get('id') for record in rules if is_stopping(record)]})
    return rows


def base_ids(root, ref, registry):
    """The record ids of rules.catalog at a git ref (local git only); None when the ref has no rules registry."""
    shown = subprocess.run(['git', '-C', str(root), 'show', f'{ref}:{registry}'], capture_output=True, text=True)
    if shown.returncode:
        known = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}'],
                               capture_output=True, text=True)
        if known.returncode:
            raise ValueError(f'--base {ref} is not a commit of {root}')
        return None
    document = json.loads(shown.stdout)
    catalog = document.get('properties', {}).get(f'{OWNER}.catalog', {}).get('default') or []
    return sorted(record['id'] for record in catalog if isinstance(record, dict) and 'id' in record)


def refusals(report):
    """What refuse mode refuses: a stopping record with a gap, an unanswered question, no measurement or no root cause;
    a stop without a question (no record); a retirement without its recorded decision; a record that left the catalog
    without a retirement."""
    stopping, retired = set(report['stopping_ids']), set(report['retired_ids'])
    found = [f'{ident} can stop a flow and has {len(gaps)} gap(s)' for ident, gaps in report['gaps'].items()
             if ident in stopping and gaps]
    found += [f'{ident} is retired without a recorded decision' for ident, gaps in report['gaps'].items()
              if ident in retired and gaps]
    found += [f'{ident} can stop a flow and its question has no answer' for ident in report['unanswered']
              if ident in stopping]
    found += [f'{row["id"]} {row["finding"]}' for row in report['accidents']]
    found += [f'{ref} can stop a flow without a question (no active record lists it)' for ref in report['unregistered']]
    found += [f'{ident} left rules.catalog without a retirement' for ident in report['deleted']]
    return found


def check(world, mode=None, base=None):
    """The report: every finding and its counts; `exit` is 1 only in refuse mode with something to refuse."""
    mode = mode or world.settings['check_mode']
    gaps, seen = {}, set()
    for index, record in enumerate(world.records):
        ident = record.get('id') or f'record #{index}'
        found = record_gaps(record, world) + ([f'id {ident} appears twice in rules.catalog'] if ident in seen else [])
        seen.add(ident)
        if found:
            gaps[ident] = gaps.get(ident, []) + found
    live = active(world)
    found = discovered(world.root, world.settings['stop_patterns'])
    missing = unregistered(world, found)
    findings = premise_findings(world)
    rows = stale(world)
    deleted = sorted(set(base) - seen) if base is not None else []
    report = {
        'today': world.today.isoformat(), 'mode': mode, 'registry': world.registry, 'gaps': gaps,
        'due': [{'id': record.get('id'), 'review_by': record.get('review_by'), 'days': days} for record, days in due(world)],
        'ending': ending(world), 'discovered': found, 'unregistered': missing, 'accidents': accidents(world),
        'unanswered': [record.get('id') for record in unanswered(world)], 'premise_findings': findings, 'stale': rows,
        'deleted': deleted, 'base_given': base is not None, 'premise_errors': world.premise_errors,
        'stopping_ids': sorted(record.get('id') for record in live if is_stopping(record)),
        'retired_ids': sorted(record.get('id') for record in world.records if not is_active(record)),
    }
    report['refusals'] = refusals(report)
    report['counts'] = {
        'records': len(world.records), 'active': len(live), 'retired': len(world.records) - len(live),
        'stopping': len(report['stopping_ids']), 'gaps': sum(len(items) for items in gaps.values()),
        'records_with_gaps': len(gaps), 'stopping_with_gaps': len(set(gaps) & set(report['stopping_ids'])),
        'due': len(report['due']), 'ending': len(report['ending']), 'unanswered': len(report['unanswered']),
        'unmeasured_stops': len([row for row in report['accidents'] if 'never been measured' in row['finding']]),
        'stops_without_root_cause': len([row for row in report['accidents'] if 'no root cause' in row['finding']]),
        'discovered_stops': len(found), 'registered_stops': len(found) - len(missing), 'unregistered_stops': len(missing),
        'no_premise': len([row for row in findings if row['premise'] is None]),
        'on_stale_premise': len({row['id'] for row in findings if row['premise']}),
        'stopping_on_stale_premise': len({row['id'] for row in findings if row['premise'] and row['stops']}),
        'stale_premises': len(rows), 'premise_register_errors': len(world.premise_errors),
        'deleted_without_retirement': len(deleted), 'refusals': len(report['refusals']),
    }
    report['exit'] = int(mode == REFUSE and bool(report['refusals']))
    return report


def record_answer(world, ident, text, by, on):
    """Append {on, by, text} to a record's question in the rules registry file, keeping its layout (a local write)."""
    path = world.root / world.registry
    source = path.read_text(encoding='utf-8')
    document = json.loads(source)
    record = next(item for item in document['properties'][f'{OWNER}.catalog']['default'] if item.get('id') == ident)
    question = record.setdefault('question', {})
    question.setdefault('answers', []).append({'on': on.isoformat(), 'by': by, 'text': text})
    indent = INDENT.search(source)
    path.write_text(json.dumps(document, indent=len(indent.group(1)) if indent else None, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    return record


def census_group(world, group_id):
    """(group, census rows) of a group of the RULE-AUDIT census, None when groups or census do not hold it. Raises
    FileNotFoundError naming the file when either file is absent. Read only: census rows are answered by the audits."""
    loaded = []
    for name in ('groups_file', 'census_file'):
        path = world.root / world.settings[name]
        if not path.is_file():
            raise FileNotFoundError(f'{world.settings[name]} is absent')
        loaded.append(json.loads(path.read_text(encoding='utf-8')))
    groups, census = loaded
    groups = groups.get('groups', groups) if isinstance(groups, dict) else groups
    if isinstance(groups, dict):
        group = groups.get(group_id)
        group = dict(group, id=group_id) if isinstance(group, dict) else None
    else:
        group = next((item for item in groups if isinstance(item, dict) and item.get('id') == group_id), None)
    if group is None:
        return None
    rows = census.get('rows', census) if isinstance(census, dict) else census
    rows = [row for row in rows if isinstance(row, dict)]
    listed = next((group[key] for key in GROUP_ROWS if isinstance(group.get(key), list)), None)
    if listed is None:
        return group, [row for row in rows if row.get('group') == group_id]
    by_id = {row.get('id'): row for row in rows}
    names = [item.get('id') if isinstance(item, dict) else item for item in listed]
    return group, [by_id.get(name, {'id': name, 'question': None}) for name in names]


# The command line.

def change_line(item, world):
    return (f'{item["id"]}: {item["reason"]} -> in {world.registry} ({OWNER}.catalog) set '
            f'{json.dumps(item["change"], ensure_ascii=False)} and replace {PENDING_DECISION} with the decision that '
            f'retires it, a row of {world.settings["decision_register"]}')


def premise_line(ident, world):
    premise = world.premises.get(ident)
    if premise is None:
        return f'{ident}: not in the premise register'
    return (f'{ident} {premise.get("status")} ({premise.get("radius")}, {premise_date(premise) or "undated"}): '
            f'{premise.get("statement")}')


def answer_line(answer):
    return f'{answer.get("on")} {answer.get("by")}: {answer.get("text")}' if answer else 'none yet'


def print_list(world, out):
    for record in world.records:
        stops = 'stops' if is_stopping(record) else 'reports'
        print(f'{record.get("id")} {record.get("status", ACTIVE)} {stops} review_by {record.get("review_by")} premises '
              f'{",".join(record.get("premises") or []) or "none"} gaps {len(record_gaps(record, world))}: '
              f'{record.get("statement")}', file=out)
    live = active(world)
    print(f'rules: {len(world.records)} (active {len(live)}, retired {len(world.records) - len(live)}, stopping '
          f'{len([record for record in live if is_stopping(record)])})', file=out)


def print_show(world, record, out):
    for field, value in record.items():
        if field == 'where':
            print('where:', file=out)
            for ref in value if isinstance(value, list) else [value]:
                print(f'  {ref} ({ref_state(world.root, ref)})', file=out)
        elif field == 'premises':
            print('premises:', file=out)
            for cited in value if isinstance(value, list) else [value]:
                print(f'  {premise_line(cited, world)}', file=out)
        elif field == 'question':
            print(f'question: {value.get("text") if isinstance(value, dict) else value}', file=out)
            print(f'  latest answer ({len(answers(record))} in all): {answer_line(latest_answer(record))}', file=out)
        elif isinstance(value, dict):
            print(f'{field}:', file=out)
            for key, item in value.items():
                print(f'  {key}: {item if isinstance(item, str) else json.dumps(item)}', file=out)
        else:
            print(f'{field}: {value if isinstance(value, str) else json.dumps(value)}', file=out)
    if is_stopping(record) and 'stop_record' not in record:
        print('stop_record: missing (the rule stops the flow and has never been measured)', file=out)
    print(f'end condition: {(end_reached(record, world) if is_active(record) else None) or "not reached"}', file=out)
    gaps = record_gaps(record, world)
    for gap in gaps:
        print(f'GAP {gap}', file=out)
    print(f'rule {record.get("id")}: {len(record.get("premises") or [])} premise(s), {len(answers(record))} answer(s), '
          f'{len(gaps)} gap(s)', file=out)


def print_question(world, record, out):
    question = record.get('question') if isinstance(record.get('question'), dict) else {}
    print(f'{record.get("id")}: {question.get("text") or "no standing question (a gap)"}', file=out)
    created = record.get('created') if isinstance(record.get('created'), dict) else {}
    print(f'  owner {record.get("owner")}; created {created.get("on")} by {created.get("by")}; review_by '
          f'{record.get("review_by")}', file=out)
    if is_stopping(record):
        print(f'  stop_record: {json.dumps(record.get("stop_record"), ensure_ascii=False)}', file=out)
    for cited in record.get('premises') or []:
        print(f'  premise {premise_line(cited, world)}', file=out)
    for answer in answers(record):
        print(f'  answer {answer_line(answer)}', file=out)
    print(f'question {record.get("id")}: {len(answers(record))} answer(s)', file=out)


def print_group(group, rows, out):
    print(f'{group.get("id")}: {group.get("title") or ""} ({len(rows)} census row(s), read only)', file=out)
    for row in rows:
        facts = '; '.join(f'{field} {json.dumps(row.get(field), ensure_ascii=False)}' for field in CENSUS_FIELDS)
        print(f'{row.get("id")}: {facts}', file=out)
        print(f'  question: {row.get("question") or "none (a finding)"}', file=out)
    asked = len([row for row in rows if not text_missing(row.get('question'))])
    print(f'question {group.get("id")}: {len(rows)} row(s), {asked} with a question', file=out)


def print_due(world, out):
    overdue = due(world)
    for record, days in overdue:
        print(f'DUE {record.get("id")}: review_by {record.get("review_by")} passed {days} day(s) ago; review it (set '
              f'last_reviewed and a new review_by) or retire it', file=out)
    silent = [record for record, _ in overdue if not answers(record)]
    for record in silent:
        question = record.get('question') if isinstance(record.get('question'), dict) else {}
        print(f'UNANSWERED {record.get("id")}: past its review date and its question has no answer: '
              f'{question.get("text")}', file=out)
    proposals = ending(world)
    for item in proposals:
        print(f'END {change_line(item, world)}', file=out)
    names = {record.get('id') for record, _ in overdue} | {item['id'] for item in proposals}
    print(f'rules due: {len(names)} (review passed {len(overdue)}, of them unanswered {len(silent)}, ending '
          f'{len(proposals)})', file=out)


def print_retired(world, out):
    records = [record for record in world.records if not is_active(record)]
    for record in records:
        retired = record.get('retired') if isinstance(record.get('retired'), dict) else {}
        gaps = retirement_gaps(record, world)
        print(f'{record.get("id")} retired {retired.get("on")} by {retired.get("by")}: {retired.get("reason")}'
              + (f' [{"; ".join(gaps)}]' if gaps else ''), file=out)
    print(f'rules retired: {len(records)}', file=out)


def print_stale(world, out):
    rows = stale(world)
    for row in rows:
        print(f'{row["premise"]} {row["label"]} ({row["radius"]}): rules {len(row["rules"])} '
              f'[{", ".join(row["rules"]) or "none"}]: {row["statement"]}', file=out)
    for row in rows:
        for ident in row['stopping']:
            print(f'STOPS {ident} rests on {row["premise"]} {row["label"]}: {row["statement"]}', file=out)
    cited = {ident for row in rows for ident in row['rules']}
    stopping = {ident for row in rows for ident in row['stopping']}
    print(f'stale premises: {len(rows)} (cited by {len(cited)} active rule(s), {len(stopping)} of them stopping)', file=out)


def print_check(report, world, out):
    counts = report['counts']
    print(f'rules check: mode {report["mode"]}, today {report["today"]}, registry {report["registry"]}', file=out)
    for ident, gaps in sorted(report['gaps'].items()):
        for gap in gaps:
            print(f'GAP {ident}: {gap}', file=out)
    for item in report['due']:
        print(f'DUE {item["id"]}: review_by {item["review_by"]} passed {item["days"]} day(s) ago', file=out)
    for item in report['ending']:
        print(f'END {change_line(item, world)}', file=out)
    for ident in report['unanswered']:
        print(f'UNANSWERED {ident}: its question has no answer', file=out)
    for row in report['accidents']:
        print(f'ACCIDENT {row["id"]}: {row["finding"]}', file=out)
    for ref in report['unregistered']:
        print(f'UNREGISTERED {ref}: a stop without a question (no active record lists it)', file=out)
    for row in report['premise_findings']:
        print(f'PREMISE {row["id"]}{" (stops)" if row["stops"] else ""}: '
              + (row['finding'] if row['premise'] is None else f'rests on {row["premise"]} {row["finding"]}'), file=out)
    for ident in report['deleted']:
        print(f'DELETED {ident}: left {OWNER}.catalog without a retirement', file=out)
    for error in report['premise_errors']:
        print(f'REGISTER {error}', file=out)
    print(f'records: {counts["records"]} (active {counts["active"]}, retired {counts["retired"]}, stopping '
          f'{counts["stopping"]}); gaps: {counts["gaps"]} in {counts["records_with_gaps"]} record(s), '
          f'{counts["stopping_with_gaps"]} stopping', file=out)
    print(f'review: due {counts["due"]}, ending (proposed retirements) {counts["ending"]}, questions unanswered '
          f'{counts["unanswered"]}', file=out)
    print(f'stops: {counts["discovered_stops"]} found by {OWNER}.stop_patterns, {counts["registered_stops"]} registered, '
          f'{counts["unregistered_stops"]} without a question; {counts["unmeasured_stops"]} never measured, '
          f'{counts["stops_without_root_cause"]} without a root cause', file=out)
    print(f'premises: {counts["no_premise"]} rule(s) cite none, {counts["on_stale_premise"]} rest on a stale premise '
          f'({counts["stopping_on_stale_premise"]} stopping); {counts["stale_premises"]} stale premise(s) in the register',
          file=out)
    print('deleted without retirement: ' + (str(counts['deleted_without_retirement']) if report['base_given']
                                            else 'not judged (no --base)'), file=out)
    print(f'{"refuses" if report["mode"] == REFUSE else "refuse mode would refuse"}: {counts["refusals"]}', file=out)
    print(f'rules check: {counts["records"]} record(s), {counts["gaps"]} gap(s), {counts["due"]} due, {counts["ending"]} '
          f'ending, {counts["unanswered"]} unanswered, {counts["unregistered_stops"]} stop(s) without a question, '
          f'{counts["on_stale_premise"]} on stale premises, {counts["stale_premises"]} stale premise(s); exit '
          f'{report["exit"]}', file=out)


def day_arg(text):
    found = date_of(text)
    if found is None:
        raise argparse.ArgumentTypeError(f'{text!r} is not a real YYYY-MM-DD date')
    return found


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--root', type=Path, help='the checkout to judge (default: this one)')
    common.add_argument('--today', type=day_arg, help='the date to judge at, YYYY-MM-DD (default: today, UTC)')
    found = argparse.ArgumentParser(prog='scripts/rule', description=__doc__.split('\n\n', 1)[0])
    commands = found.add_subparsers(dest='command', required=True)
    commands.add_parser('list', parents=[common], help='every record, one line each')
    show = commands.add_parser('show', parents=[common], help="one record's fields, question and premises")
    show.add_argument('id')
    commands.add_parser('due', parents=[common], help='review dates passed, unanswered questions, ends met, code gone')
    commands.add_parser('retired', parents=[common], help='retired records and their decisions')
    commands.add_parser('stale', parents=[common], help='refuted, unsettled or undated premises and the rules on them')
    asked = commands.add_parser('question', parents=[common], help="a record's or a census group's standing question")
    asked.add_argument('target', help='a record id, or a group id of rules.groups_file')
    asked.add_argument('--answer', help="record this answer to the record's question (rules.json, local write)")
    asked.add_argument('--by', help='who answers (with --answer)')
    asked.add_argument('--on', type=day_arg, help='the answer date (with --answer; default: --today)')
    run = commands.add_parser('check', parents=[common], help='the whole report with its counts')
    run.add_argument('--mode', choices=(REPORT, REFUSE), help=f'default: {OWNER}.check_mode')
    run.add_argument('--base', help='a git ref: records present there and absent here left without a retirement')
    run.add_argument('--json', action='store_true', help='print the report as JSON')
    return found


def question_command(command, args, world, out):
    record = next((item for item in world.records if item.get('id') == args.target), None)
    if record is None:
        if args.answer is not None:
            command.error(f'--answer records the answer of a rule record; {args.target} is not one (census rows are '
                          'answered by their group audits)')
        try:
            found = census_group(world, args.target)
        except FileNotFoundError as error:
            command.error(f'{args.target} is not a record of {world.registry}, and {error}')
        if found is None:
            command.error(f'{args.target} is neither a record of {world.registry} nor a group of '
                          f'{world.settings["groups_file"]}')
        print_group(*found, out)
        return 0
    if args.answer is not None:
        if text_missing(args.answer) or text_missing(args.by):
            command.error('--answer needs a text and --by who answers')
        record = record_answer(world, args.target, args.answer, args.by, args.on or world.today)
    elif args.by or args.on:
        command.error('--by and --on go with --answer')
    print_question(world, record, out)
    return 0


def main(argv=None, out=sys.stdout):
    config.pin_store('file')  # local files only: the checkout's registry and local log, never the forge
    command = parser()
    args = command.parse_args(argv)
    world = load((args.root or ROOT).resolve(), args.today)
    if args.command == 'question':
        return question_command(command, args, world, out)
    if args.command == 'show':
        record = next((item for item in world.records if item.get('id') == args.id), None)
        if record is None:
            command.error(f'no record {args.id} in {world.registry}')
        print_show(world, record, out)
    elif args.command in ('list', 'due', 'retired', 'stale'):
        {'list': print_list, 'due': print_due, 'retired': print_retired, 'stale': print_stale}[args.command](world, out)
    else:
        try:
            base = base_ids(world.root, args.base, world.registry) if args.base else None
        except ValueError as error:
            command.error(str(error))
        report = check(world, args.mode, base)
        if args.json:
            print(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False), file=out)
        else:
            print_check(report, world, out)
        return report['exit']
    return 0


if __name__ == '__main__':
    sys.exit(main())
