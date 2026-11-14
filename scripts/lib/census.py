"""The literal census of each unit (CENSO-NO-MANIFESTO; D-063, D-064 a, D-067): its record, its reader, its writer.

The census has two lists: the literal catalogs (a file whose literals are the documented keys of a domain) and the
absolute baseline (a file whose remaining offenders are still allowed, per kind and value). They lived in one file
per census area under scripts/lib/literal-catalogs/ and scripts/lib/absolute-literals-baseline/, and every unit with
an entry wrote into a file it did not own: N writers of one file make N(N-1)/2 pairs that can collide. Each unit now
keeps its own append-only record, units/<id>/census.jsonl (census.record_file): one event per line, shaped by
contracts/units/census.v1.json, chained by digest (scripts/lib/audit_chain.py). The live census of a unit is the fold
of its events. The per-area view is derived (scripts/generate census, never committed) and the readers build it in
memory from the tree, so a verdict depends on the checkout alone. A census entry is an input to a verdict: kept in a
remote store, the same commit could be judged differently at two times. The API is the write path and the query path,
not a network hop.

Until scripts/census migrate has emptied them, the readers also merge the old per-area files (census.<census>_legacy_dir). A path
held in both forms is refused, and so is an area file that the base does not have, so once the migration deletes them
none comes back.

Library: area(path), record_path, read_trail, fold, records(root, ref), live(root, ref), legacy(root, ref),
entries(root, census, ref), areas(root, census, ref), check(root, base), scan(root), engine_scan(root),
append(root, unit, events).

  scripts/census add <path> --why W [--actor A] [--catalog --domain D... --holds H [--builder B...]
                 [--generated-from S] [--replace]]
  scripts/census remove <path> --why W [--actor A] [--catalog]
  scripts/census sync [--unit U] --why W [--actor A]     baseline entries brought to the scan (set, add, remove)
  scripts/census migrate <area> --why W [--actor A]      an old per-area file's entries moved into the unit records
  scripts/census list [--unit U] [--census catalog|baseline] [--paths]
  scripts/census show <path>
  scripts/census check [--base REF]
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import audit_chain
import config
import json_schema
import units

ROOT = Path(__file__).resolve().parent.parent.parent
CENSUSES = ('catalog', 'baseline')
CATALOG, BASELINE = CENSUSES
LEGACY_KEYS = {CATALOG: 'catalogs', BASELINE: 'files'}  # where the old per-area shapes kept their entries
ADD, SET, REMOVE = 'add', 'set', 'remove'
SCAN_LINE = re.compile(r'^(?P<path>[^:\s]+):(?P<line>\d+): (?P<kind>[a-z_]+) (?P<text>".*") \((?P<role>[^()]*)\)$')
FIX = 'the census is written by scripts/census (add, remove, sync, migrate), never by hand'


class CensusError(ValueError):
    pass


def _registry_root(root, owner):
    """root when its registry declares the owner's file, else None (this checkout's): a fixture without it reads ours."""
    return root if root is not None and (Path(root) / 'config' / 'registry' / f'{owner}.json').is_file() else None


def setting(name, root=None):
    return config.get(f'census.{name}', _registry_root(root, 'census'))


def _manifest_dir(root):
    return units.setting('manifest_dir', _registry_root(root, 'units'))


def _root(root):
    return ROOT if root is None else Path(root)


def area(path):
    """The census area of a path: the name of the folder that holds it; a file at the repository root is its own area.
    OU-DECOUPLE F5 (D-113): the area no longer mirrors the deleted product's TypeScript scanner (a folder of its
    source tree); it is one name, so the per-area view writes one file per area."""
    folder = PurePosixPath(path).parent.name
    return folder or path


def record_path(root, unit):
    root = _root(root)
    return root / _manifest_dir(root) / unit / setting('record_file', root)


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def read_trail(text):
    """The events of a record's text, one JSON object per line; CensusError on a line that is not JSON."""
    trail = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            trail.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise CensusError(f'line {number} is not JSON ({error.msg})') from error
    return trail


def fold(trail):
    """({census: {path: entry}}, errors) of a record's events in order."""
    state, errors = {census: {} for census in CENSUSES}, []
    for event in trail:
        if not isinstance(event, dict) or event.get('census') not in state:
            continue
        held, path, op = state[event['census']], event.get('path'), event.get('op')
        where = f'event {event.get("n")} ({op} {event["census"]} {path})'
        if op == ADD and path in held:
            errors.append(f'{where}: the entry is already live; a change is a set')
        elif op in (SET, REMOVE) and path not in held:
            errors.append(f'{where}: there is no live entry to {op}')
        if op == REMOVE:
            held.pop(path, None)
        elif op in (ADD, SET):
            held[path] = event.get('entry')
    return state, errors


def _record_texts(root, ref=None):
    """{unit: text} of every record in the checkout, or at ref."""
    root = _root(root)
    folder, name = _manifest_dir(root), setting('record_file', root)
    if ref is None:
        return {path.parent.name: path.read_text(encoding='utf-8')
                for path in sorted((root / folder).glob(f'*/{name}')) if path.is_file()}
    listed = _git(root, 'ls-tree', '-r', '--name-only', ref, '--', folder)
    if listed.returncode:
        raise CensusError(f'cannot list {folder} at {ref}')
    found = {}
    for path in map(PurePosixPath, listed.stdout.split()):
        if path.name == name and path.parent.parent.as_posix() == folder:
            found[path.parent.name] = _git(root, 'show', f'{ref}:{path}').stdout
    return found


def records(root=None, ref=None):
    """{unit: trail} of every readable record; an unreadable one is check()'s to report."""
    found = {}
    for unit, text in _record_texts(root, ref).items():
        try:
            found[unit] = read_trail(text)
        except CensusError:
            continue
    return found


def live(root=None, ref=None):
    """{census: {path: (unit, entry)}} folded from every unit record."""
    found = {census: {} for census in CENSUSES}
    for unit, trail in records(root, ref).items():
        state, _ = fold(trail)
        for census, held in state.items():
            for path, entry in held.items():
                found[census][path] = (unit, entry)
    return found


def _legacy_texts(root, census, ref=None):
    """{area: text} of the old per-area files of one census, in the checkout or at ref (subfolders are other lists)."""
    root = _root(root)
    folder = setting(f'{census}_legacy_dir', root)
    if ref is None:
        found = root / folder
        return {path.stem: path.read_text(encoding='utf-8') for path in sorted(found.glob('*.json'))} \
            if found.is_dir() else {}
    listed = _git(root, 'ls-tree', '--name-only', f'{ref}:{folder}')
    if listed.returncode:
        return {}
    return {Path(name).stem: _git(root, 'show', f'{ref}:{folder}/{name}').stdout
            for name in sorted(listed.stdout.split()) if name.endswith('.json')}


def legacy(root=None, ref=None):
    """{census: {area: {path: entry}}} of the old per-area files still present."""
    root = _root(root)
    found = {}
    for census in CENSUSES:
        key = LEGACY_KEYS[census]
        found[census] = {name: json.loads(text).get(key) or {} for name, text in _legacy_texts(root, census, ref).items()}
    return found


def entries(root=None, census=BASELINE, ref=None):
    """{path: entry} of one census: the unit records, merged with the old per-area files during the migration."""
    merged = {}
    for held in legacy(root, ref)[census].values():
        merged.update(held)
    merged.update({path: entry for path, (_, entry) in live(root, ref)[census].items()})
    return dict(sorted(merged.items()))


def areas(root=None, census=BASELINE, ref=None):
    """{area: {path: entry}} of one census: the per-area view, built in memory."""
    grouped = {}
    for path, entry in entries(root, census, ref).items():
        grouped.setdefault(area(path), {})[path] = entry
    return dict(sorted(grouped.items()))


def _owners(root, path):
    try:
        return units.units_of(path, root)
    except units.UnitError as error:
        raise CensusError(str(error)) from error


def _shape_errors(event, schema, where):
    errors = [f'{where}: {error}' for error in json_schema.validate(schema, event)]
    if errors or not isinstance(event, dict):
        return errors
    entry, op = event.get('entry'), event['op']
    if op == REMOVE and entry is not None:
        errors.append(f'{where}: a remove carries no entry')
    elif op != REMOVE and entry is None:
        errors.append(f'{where}: an {op} carries the entry')
    elif op != REMOVE and (event['census'] == CATALOG) != ('holds' in entry):
        errors.append(f'{where}: a {event["census"]} entry has the shape of the other census')
    elif op != REMOVE and event['census'] == BASELINE and not entry:
        errors.append(f'{where}: an empty baseline entry is a remove')
    return errors


def check(root=None, base=None):
    """Every error of the census records and of the old per-area files: shape, canonical text, digest chain, fold,
    ownership, append-only against base, and no per-area file that the base does not have."""
    root = _root(root)
    errors = []
    schema_path = root / setting('schema', root)
    schema = json.loads((schema_path if schema_path.is_file() else ROOT / setting('schema', root)).read_text(encoding='utf-8'))
    algorithm, genesis = setting('digest_algorithm', root), setting('genesis_digest', root)
    texts = _record_texts(root)
    known = units.manifests(root) if texts else {}
    try:
        before = _record_texts(root, base) if base else {}
    except CensusError as error:
        errors.append(f'census: {error}; the census fails closed')
        before = {}
    held = {census: {} for census in CENSUSES}
    for unit, text in texts.items():
        where = record_path(root, unit).relative_to(root).as_posix()
        if unit not in known:
            errors.append(f'{where}: no unit manifest units/{unit}/unit.json')
            continue
        try:
            trail = read_trail(text)
        except CensusError as error:
            errors.append(f'{where}: {error}; {FIX}')
            continue
        shape = [error for index, event in enumerate(trail, start=1) for error in _shape_errors(event, schema, f'{where} event {index}')]
        errors += shape
        if shape:
            continue
        if audit_chain.dump_trail(trail) != text:
            errors.append(f'{where}: not the writer\'s canonical text (a hand edit); {FIX}')
        errors += [f'{error}; {FIX}' for error in audit_chain.chain_errors(trail, where, algorithm, genesis)]
        state, fold_errors = fold(trail)
        errors += [f'{where}: {error}' for error in fold_errors]
        if unit in before:
            try:
                old = read_trail(before[unit])
            except CensusError:
                old = None
            if old is not None and trail[:len(old)] != old:
                errors.append(f'{where}: the {len(old)} events of {base} are not its first {len(old)} events; a record '
                              f'is append-only: undo a change with a new event; {FIX}')
        for census, found in state.items():
            for path in found:
                owners = _owners(root, path)
                if owners != [unit]:
                    who = ', '.join(owners) if owners else 'no unit'
                    errors.append(f'{where}: {census} entry {path} belongs to {who}, not {unit}; every entry lives in '
                                  f'the record of the one unit whose paths match it (units.units_of)')
                held[census][path] = unit
    current, has_units = legacy(root), (root / _manifest_dir(root)).is_dir()
    previous = legacy(root, base) if base else None
    for census in CENSUSES:
        folder = setting(f'{census}_legacy_dir', root)
        for name, found in current[census].items():
            where = f'{folder}/{name}.json'
            if previous is not None and name not in previous[census]:
                errors.append(f'{where}: a per-area file is a derived view (scripts/generate census), never a new '
                              f'committed file; {FIX}')
            for path in found:
                if path in held[census]:
                    errors.append(f'{where}: {path} is also in the record of {held[census][path]}; finish '
                                  f'`scripts/census migrate {name}`')
                owners = _owners(root, path) if has_units else [None]
                if len(owners) != 1:
                    who = ', '.join(owners) if owners else 'no unit'
                    errors.append(f'{where}: {path} belongs to {who}; every entry must land in exactly one unit')
    return errors


def today():
    return datetime.now(timezone.utc).date().isoformat()


def actor(root=None, given=None):
    """--actor, else the checkout's git user.email, else $USER."""
    if given:
        return given
    email = _git(_root(root), 'config', 'user.email').stdout.strip()
    return email or os.environ.get('USER') or 'unknown'


def append(root, unit, events, at=None):
    """Append events (dicts with op, census, path, entry?, why, by) to a unit's record, chained, after checking that
    the fold accepts them. Returns the record's path."""
    root = _root(root)
    path = record_path(root, unit)
    trail = read_trail(path.read_text(encoding='utf-8')) if path.is_file() else []
    algorithm, genesis = setting('digest_algorithm', root), setting('genesis_digest', root)
    for event in events:
        entry = {'n': len(trail) + 1, 'at': at or today(), 'by': event['by'], 'op': event['op'],
                 'census': event['census'], 'path': event['path'], 'why': event['why'],
                 'prev': trail[-1]['digest'] if trail else genesis}
        if event.get('entry') is not None:
            entry['entry'] = event['entry']
        entry['digest'] = audit_chain.entry_digest(entry, algorithm)
        trail.append(entry)
    _, errors = fold(trail)
    if errors:
        raise CensusError('; '.join(errors))
    path.write_text(audit_chain.dump_trail(trail), encoding='utf-8')
    return path


def owner(root, path):
    """The one unit of a path; CensusError for none or several."""
    found = _owners(root, path)
    if len(found) != 1:
        raise CensusError(f'{path} belongs to {", ".join(found) if found else "no unit"}; a census entry lands in '
                          f'exactly one unit (add the path to one manifest\'s paths)')
    return found[0]


def _scan_key(found):
    """The census key of a literal_census key (`number 4321`, `host "x"`): the value always as a JSON string, the shape
    a scanner line carries (SCAN_LINE) and contracts/units/census.v1.json names (`number "4321"`)."""
    kind, _, value = found.partition(' ')
    value = json.loads(value)
    return f'{kind} {json.dumps(value if isinstance(value, str) else json.dumps(value), ensure_ascii=False)}'


def engine_scan(root):
    """{path: {`<kind> "<value>"`: count}} of the engine's own literal scan (literal_census.occurrences: the files
    config.literal_check_* names, judged by literals.*), the scan used when census.scan_argv declares none."""
    import literal_census  # imports units and config_check; loaded only when a baseline is measured
    counts = {}
    for path, (_, held) in literal_census.occurrences(_root(root)).items():
        for found, lines in held.items():
            key = _scan_key(found)
            counts.setdefault(path, {})[key] = counts.get(path, {}).get(key, 0) + len(lines)
    return {path: dict(sorted(values.items())) for path, values in sorted(counts.items())}


def scan(root=None):
    """{path: {`<kind> <value as JSON>`: count}} of the absolute scan. census.scan_argv names a product's scanner,
    which prints one `path:line: kind "value" (role)` line per offender; empty (the engine's default, OU-DECOUPLE F5,
    D-113: the only declared scanner was the deleted product's), the scan is the engine's own (engine_scan), so
    scripts/census add and sync measure the counts and nobody types them."""
    root = _root(root)
    argv = setting('scan_argv', root)
    if not argv:
        return engine_scan(root)
    try:
        done = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                              timeout=setting('scan_timeout', root))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CensusError(f'the absolute scan did not run: {error}') from error
    if done.returncode:
        raise CensusError(f'the absolute scan failed: {done.stderr.strip() or done.stdout.strip()}')
    counts = {}
    for line in done.stdout.splitlines():
        found = SCAN_LINE.match(line)
        if not found:
            raise CensusError(f'the absolute scan printed a line that is not an offender: {line}')
        key = f'{found["kind"]} {found["text"]}'
        counts.setdefault(found['path'], {})[key] = counts.get(found['path'], {}).get(key, 0) + 1
    return {path: dict(sorted(values.items())) for path, values in sorted(counts.items())}


def _catalog_entry(args):
    entry = {'domains': args.domain, 'holds': args.holds}
    if args.generated_from:
        entry['generatedFrom'] = args.generated_from
    if args.builder:
        entry['builders'] = args.builder
    return entry


def _held_in_legacy(root, census, path):
    for name, found in legacy(root)[census].items():
        if path in found:
            return name
    return None


def command_add(root, args):
    census = CATALOG if args.catalog else BASELINE
    unit = owner(root, args.path)
    where = _held_in_legacy(root, census, args.path)
    if where:
        raise CensusError(f'{args.path} is held in the {census} area file {where}.json; run `scripts/census migrate '
                          f'{where}` first')
    if census == CATALOG:
        if not args.domain or not args.holds:
            raise CensusError('a catalog entry needs --domain and --holds')
        entry = _catalog_entry(args)
    else:
        entry = scan(root).get(args.path)
        if not entry:
            raise CensusError(f'the absolute scan finds no offender in {args.path}; there is nothing to allow')
    is_live = args.path in live(root)[census]
    if is_live and not args.replace:
        raise CensusError(f'{args.path} already has a live {census} entry in {unit}; pass --replace to change it')
    op = SET if is_live else ADD
    written = append(root, unit, [{'op': op, 'census': census, 'path': args.path, 'entry': entry, 'why': args.why,
                                   'by': actor(root, args.actor)}])
    return [f'{op} {census} {args.path} -> {written.relative_to(root).as_posix()}']


def command_remove(root, args):
    census = CATALOG if args.catalog else BASELINE
    held = live(root)[census].get(args.path)
    if held is None:
        raise CensusError(f'{args.path} has no live {census} entry in any unit record')
    written = append(root, held[0], [{'op': REMOVE, 'census': census, 'path': args.path, 'why': args.why,
                                      'by': actor(root, args.actor)}])
    return [f'remove {census} {args.path} -> {written.relative_to(root).as_posix()}']


def command_sync(root, args):
    """Every baseline entry of the scope brought to the scan: a changed file is set, a file with no offender left is
    removed, an offending file nobody holds is added (the ratchet of structure-check judges the growth)."""
    counted, held = scan(root), live(root)[BASELINE]
    in_legacy = {path for found in legacy(root)[BASELINE].values() for path in found}
    by, lines, events = actor(root, args.actor), [], {}
    for path in sorted(set(counted) | set(held)):
        if path in in_legacy:
            continue
        unit = held[path][0] if path in held else owner(root, path)
        if args.unit and unit != args.unit:
            continue
        want, have = counted.get(path), held.get(path, (None, None))[1]
        if want == have:
            continue
        op = REMOVE if not want else (SET if have else ADD)
        event = {'op': op, 'census': BASELINE, 'path': path, 'why': args.why, 'by': by}
        if want:
            event['entry'] = want
        events.setdefault(unit, []).append(event)
        lines.append(f'{op} baseline {path} ({unit})')
    for unit, found in sorted(events.items()):
        append(root, unit, found)
    skipped = sorted(path for path in in_legacy if path in counted or path in held)
    if skipped:
        lines.append(f'{len(skipped)} path(s) still in a per-area file were left alone; `scripts/census migrate <area>` '
                     f'moves them')
    return lines or ['in sync']


def command_migrate(root, args):
    """Move an old per-area file's entries, both censuses, into the records of their units, and delete the file."""
    lines = []
    for census in CENSUSES:
        folder = setting(f'{census}_legacy_dir', root)
        path = Path(root) / folder / f'{args.area}.json'
        if not path.is_file():
            continue
        found = json.loads(path.read_text(encoding='utf-8')).get(LEGACY_KEYS[census]) or {}
        held = live(root)[census]
        events, by = {}, actor(root, args.actor)
        for entry_path, entry in sorted(found.items()):
            if entry_path in held:
                raise CensusError(f'{entry_path} is already in the record of {held[entry_path][0]}')
            events.setdefault(owner(root, entry_path), []).append(
                {'op': ADD, 'census': census, 'path': entry_path, 'entry': entry, 'why': args.why, 'by': by})
        for unit, chosen in sorted(events.items()):
            append(root, unit, chosen)
            lines.append(f'{census} {args.area}: {len(chosen)} entr{"y" if len(chosen) == 1 else "ies"} -> {unit}')
        path.unlink()
        lines.append(f'deleted {folder}/{args.area}.json ({len(found)} entries moved)')
    if not lines:
        raise CensusError(f'no per-area file named {args.area}.json is left')
    return lines


def command_list(root, args):
    lines = []
    for census in CENSUSES:
        if args.census and census != args.census:
            continue
        for path, (unit, _) in sorted(live(root)[census].items()):
            if not args.unit or unit == args.unit:
                lines.append(path if args.paths else f'{unit}\t{census}\t{path}')
        for name, found in sorted(legacy(root)[census].items()):
            for path in sorted(found):
                unit = owner(root, path) if not args.paths or args.unit else None
                if not args.unit or unit == args.unit:
                    lines.append(path if args.paths else f'{unit}\t{census}\t{path}\t(per-area file {name}.json)')
    return lines


def command_show(root, args):
    lines = []
    for census in CENSUSES:
        held = live(root)[census].get(args.path)
        where = _held_in_legacy(root, census, args.path)
        if held:
            lines.append(f'{census}\t{held[0]}\t{json.dumps(held[1], ensure_ascii=False, sort_keys=True)}')
            trail = records(root).get(held[0], [])
            lines += [f'  {event["n"]}\t{event["at"]}\t{event["by"]}\t{event["op"]}\t{event["why"]}'
                      for event in trail if event.get('census') == census and event.get('path') == args.path]
        elif where:
            entry = legacy(root)[census][where][args.path]
            lines.append(f'{census}\t{owner(root, args.path)}\t{json.dumps(entry, ensure_ascii=False, sort_keys=True)}'
                         f'\t(per-area file {where}.json, not yet migrated)')
    if not lines:
        raise CensusError(f'{args.path} is in neither census')
    return lines


def command_check(root, args):
    errors = check(root, args.base)
    if errors:
        raise CensusError('\n'.join(errors))
    held, old = live(root), legacy(root)
    waiting = sum(len(found) for areas_of in old.values() for found in areas_of.values())
    return [f'census: {sum(len(found) for found in held.values())} live entries in '
            f'{len({unit for found in held.values() for unit, _ in found.values()})} unit record(s), {waiting} still in '
            f'{sum(len(areas_of) for areas_of in old.values())} per-area file(s), 0 error(s)']


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/census', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, help='repository (default: this checkout)')
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add', help='add (or with --replace, set) the entry of a path')
    add.add_argument('path')
    add.add_argument('--catalog', action='store_true', help='a literal catalog entry (default: a baseline entry)')
    add.add_argument('--domain', action='append', help='a domain the catalog holds (repeat)')
    add.add_argument('--holds', help='one sentence on what the catalog holds')
    add.add_argument('--builder', action='append', help='a builder module of a schema catalog (repeat)')
    add.add_argument('--generated-from', help='the source a generator writes the catalog from')
    add.add_argument('--replace', action='store_true', help='set the live entry instead of refusing it')
    remove = commands.add_parser('remove', help='remove the live entry of a path')
    remove.add_argument('path')
    remove.add_argument('--catalog', action='store_true', help='the catalog entry (default: the baseline entry)')
    sync = commands.add_parser('sync', help='bring the baseline entries to the absolute scan')
    sync.add_argument('--unit', help='only this unit\'s entries')
    migrate = commands.add_parser('migrate', help='move an old per-area file into the unit records')
    migrate.add_argument('area')
    for command in (add, remove, sync, migrate):
        command.add_argument('--why', required=True, help='the reason, recorded in the event')
        command.add_argument('--actor', help='who records it (default: git user.email, else $USER)')
    listing = commands.add_parser('list', help='every live entry: unit, census, path')
    listing.add_argument('--unit')
    listing.add_argument('--census', choices=CENSUSES)
    listing.add_argument('--paths', action='store_true', help='print the paths only')
    show = commands.add_parser('show', help='the unit, live entry and history of a path')
    show.add_argument('path')
    checking = commands.add_parser('check', help='validate every record and per-area file')
    checking.add_argument('--base', help='the ref the records must extend (append-only)')
    args = parser.parse_args(argv)
    root = (args.root or Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip() or ROOT)).resolve()
    handler = {'add': command_add, 'remove': command_remove, 'sync': command_sync, 'migrate': command_migrate,
               'list': command_list, 'show': command_show, 'check': command_check}[args.command]
    try:
        for line in handler(root, args):
            print(line)
    except (CensusError, units.UnitError, config.ConfigError) as error:
        print(f'scripts/census: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
