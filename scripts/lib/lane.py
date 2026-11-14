"""The lane brief of one queue unit: its row, the delivery contract and a worktree (VAZÃO F68).

`scripts/lane brief F68` prints a brief a fresh lane can deliver from alone: the unit's row of the VAZÃO queue
(`docs/programs/vazao/fila.md`), the rules digest of `docs/process/lane.md` (F78: lane-digest.md, 1.5 KB in place of
the 4.8 KB contract, `scripts/generate lane-digest`) and a suggested worktree with the
command that makes it. It also carries the context the row points at, so the lane opens neither fila.md, RETOMAR.md nor
DECISIONS.md (F77): the line of every D-NNN the row cites, and for every unit its "Depois de" names, the line or row that
names it and whether a commit on the base names it (`git log --first-parent --grep`). F83: it lists the tests red on
the base head, so a lane never debugs someone else's red: the open base.red the last gate verdict on that sha emitted
(GX-32, defect_detect.base_signal) and the F73 base-class cache's failures for it (defect_detect.outcome). Nothing is
written; the coordinator hands the printed text to the lane.
`scripts/lane collect <report>` closes a delivered lane from its report (VAZÃO F69, scripts/lib/lane_collect.py).
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE = Path('docs/programs/vazao/fila.md')
CONTRACT = Path('docs/process/lane.md')
DIGEST = Path('docs/process/lane-digest.md')  # generated from CONTRACT (F78)
DECISIONS = Path('docs/domain/DECISIONS.md')
RESUME = Path('docs/RETOMAR.md')
BASE = 'mod/roadmap-integration'
WORKTREE_ROOT = '/root/wt'
HOME_CHECKOUT = Path.home() / 'the-tower'  # the checkout whose .toolchain every worktree links
# Sections of lane.md; the first one is required (the brief carries the digest, F78).
SECTIONS = ('The delivery contract', 'Chaining', 'Selection holes')
UNIT = re.compile(r'^F\d+$')
NAME = re.compile(r'^[a-z0-9][a-z0-9._-]*$')  # a worktree that is not a queue unit (census, f61-2): F81
DEPENDS = re.compile(r'\b[Dd]epois d[eao]s? (.*?)(?:\.\s|\.$|$)')  # to the end of the sentence
TAG = re.compile(r'\*\*\[[^\]]*\]\*\*\s*')  # the `**[eficiência]**` tag of a row's unit cell
DECISION = re.compile(r'\bD-\d{3,}\b')
CONTEXT_LINE = 240  # chars of one decision or dependency line in the brief (F77: the brief stays small)
CONTEXT_MAX = 8  # decisions or dependencies shown; past that, the rg command that finds the rest


class BriefError(Exception):
    pass


def cells(line):
    """The cells of one markdown table row; an escaped pipe stays inside its cell."""
    body = line.strip()
    body = body[1:] if body.startswith('|') else body
    body = body[:-1] if body.endswith('|') and not body.endswith('\\|') else body
    return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', body)]


def queue_rows(text):
    """(header, {unit: cells}) of the active table: the table whose header starts with `| # |`."""
    header, rows = None, {}
    for line in text.splitlines():
        if not line.startswith('|'):
            if header and rows:
                break
            continue
        row = cells(line)
        if header is None:
            if row and row[0] == '#':
                header = row
            continue
        if UNIT.match(row[0]):
            rows[row[0]] = row
    if header is None:
        raise BriefError(f'{QUEUE}: no active table (a header starting with `| # |`)')
    return header, rows


def sections(text, names=SECTIONS):
    """The `## ` sections of lane.md whose heading starts with one of names, in names' order."""
    found = {}
    for part in re.split(r'(?m)^(?=## )', text):
        heading = part.splitlines()[0][3:] if part.startswith('## ') else ''
        for name in names:
            if heading.startswith(name) and name not in found:
                found[name] = part.rstrip() + '\n'
    if names[0] not in found:
        raise BriefError(f'{CONTRACT}: no section `## {names[0]}`')
    return [found[n] for n in names if n in found]


def depends_on(row):
    """The units a row says it comes after (`Depois de F58 e de F62`)."""
    out = []
    for m in DEPENDS.finditer(' '.join(row[1:])):
        out += [u for u in re.findall(r'F\d+', m.group(1)) if u not in out]
    return out


def clip(text, limit=CONTEXT_LINE):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def unit_pattern(unit):
    return re.compile(rf'(?<![\w-]){unit}(?!\d)')


def cited_decisions(row):
    out = []
    for d in DECISION.findall(' '.join(row[1:])):
        if d not in out:
            out.append(d)
    return out


def decision_lines(ids, text):
    """{D-NNN: `D-NNN (date): decision`} from the rows of DECISIONS.md, each clipped."""
    out = {}
    for line in text.splitlines():
        if not line.startswith('| D-'):
            continue
        row = cells(line)
        if row[0] in ids and row[0] not in out:
            out[row[0]] = clip(f'{row[0]} ({row[1]}): {row[2]}' if len(row) > 2 else line)
    return out


def naming_line(unit, sources):
    """(source, text) of the first line of sources that names unit, as a window around the name."""
    pat = unit_pattern(unit)
    for name, text in sources:
        for line in text.splitlines():
            m = pat.search(line)
            if m:
                start = max(0, m.start() - 60)
                return name, ('…' if start else '') + clip(line[start:].strip(), CONTEXT_LINE - 1)
    return None, None


def delivers(unit, subject):
    """Whether a commit subject names unit as its delivery, the way deliver reads PR titles (F60): `F58:` or `(F58`."""
    return bool(re.search(rf'(?<![\w-]){unit}:|\({unit}(?:\)|, D-\d)', subject))


def merged_commit(unit, root, base, run=subprocess.run):
    """`<sha> <subject>` of the oldest first-parent commit of the base that delivers unit (its first PR), or None.
    `git log --grep` finds the commits that name it; the subject tells a delivery from a mention (a queue close)."""
    rx = rf'(^|[^0-9A-Za-z-]){unit}([^0-9]|$)'
    for ref in (f'origin/{base}', 'HEAD'):
        try:
            done = run(['git', '-C', str(root), 'log', '--first-parent', '-E', f'--grep={rx}', '--format=%h %s',
                        ref], capture_output=True, text=True)
        except OSError:
            return None
        if done.returncode == 0:
            hits = [l for l in done.stdout.splitlines() if delivers(unit, l.partition(' ')[2])]
            return clip(hits[-1], 120) if hits else None
    return None


def context(unit, row, rows, root, base, run=subprocess.run):
    """The brief's lines for the decisions the row cites and the units it comes after (F77)."""
    out = []
    ids = cited_decisions(row)
    if ids:
        path = root / DECISIONS
        found = decision_lines(set(ids), path.read_text(encoding='utf-8')) if path.exists() else {}
        out += ['', f'## Decisions the row cites (from {DECISIONS})', '']
        out += [f'- {found.get(d, d + ": no row in " + str(DECISIONS))}' for d in ids[:CONTEXT_MAX]]
        if len(ids) > CONTEXT_MAX:
            out.append(f'- and {len(ids) - CONTEXT_MAX} more: `rg -n "{"|".join(ids[CONTEXT_MAX:])}" {DECISIONS}`')
    deps = [u for u in depends_on(row) if u != unit]
    if deps:
        texts = []
        for rel in (QUEUE, RESUME):
            if (root / rel).exists():
                lines = (root / rel).read_text(encoding='utf-8').splitlines()
                if rel == QUEUE:  # the open rows are named below by their row; the rest of fila.md by its line
                    lines = [l for l in lines if not (l.startswith('|') and cells(l)[0] in rows)]
                texts.append((rel, '\n'.join(lines)))
        out += ['', '## The units it comes after', '']
        for dep in deps[:CONTEXT_MAX]:
            if dep in rows:
                where = f'; open, row {dep}: {clip(TAG.sub("", rows[dep][1]), 120)}'
            else:
                src, line = naming_line(dep, texts)
                where = f'; {src}: {line}' if line else ''
            commit = merged_commit(dep, root, base, run)
            state = f'merged {commit}' if commit else 'not merged (no commit on the base delivers it)'
            out.append(f'- {dep}: {state}{where or ("" if commit else "; named nowhere in the queue or RETOMAR.md")}')
    return out


def base_head(root, base, run=subprocess.run):
    """The sha of origin/<base> in root, or None."""
    try:
        done = run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', f'origin/{base}^{{commit}}'],
                   capture_output=True, text=True)
    except OSError:
        return None
    sha = done.stdout.strip() if done.returncode == 0 else ''
    return sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None


def cached_reds(sha):
    """F73's cache (defect_detect.outcome, per base sha and test): the tests it last saw fail on sha, within its TTL."""
    import json
    import defect_detect
    from adapters import storage
    store = storage.open_store(defect_detect.cache_location())
    now, ttl = defect_detect._now(), defect_detect.setting('cache_ttl_s')
    found = []
    for key in store.keys(f'v{defect_detect.setting("cache_version")}/{sha}'):
        try:
            item = json.loads(store.get(key))
            if item['base_sha'] == sha and item['result'] == defect_detect.FAIL and 0 <= now - item['stored_at'] <= ttl:
                found.append(item['test'])
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(found)


def base_reds(sha, signal=None, cached=None):
    """[(test, stage, source)] red on the base head sha (F83): the open base.red of the last gate verdict on it, then
    the F73 cache's failures it does not already name. A source that cannot be read adds nothing."""
    out = []
    try:
        if signal is None:
            import defect_detect
            signal = defect_detect.base_signal
        for test, stage in sorted(signal(sha) or {}):
            out.append((test, stage, 'base.red, the last gate verdict on the base head'))
    except Exception:  # noqa: BLE001 - an unreadable signal lists nothing; the brief still prints
        pass
    try:
        named = {test for test, _, _ in out}
        out += [(test, '', 'F73 cache: it failed on the base head') for test in (cached or cached_reds)(sha)
                if test not in named]
    except Exception:  # noqa: BLE001 - an unreadable cache lists nothing
        pass
    return out


def red_section(root, base, run=subprocess.run, reds=base_reds):
    """The brief's lines for the tests red on the base head (F83)."""
    sha = base_head(root, base, run)
    if not sha:
        return ['', f'Red on the base: unknown (origin/{base} does not resolve here).']
    found = reds(sha)
    if not found:
        return ['', f'Red on the base: none known at {sha[:12]} (no open base.red, no F73 cached failure); a red '
                    'the gate names on this lane is its own unless deliver classes it base.']
    out = ['', f'## Red on the base at {sha[:12]} (not this lane\'s to debug; report it, do not fix it)', '']
    out += [f'- `{test}`{f" ({stage})" if stage else ""}: {source}' for test, stage, source in found[:CONTEXT_MAX]]
    if len(found) > CONTEXT_MAX:
        out.append(f'- and {len(found) - CONTEXT_MAX} more')
    return out


def named_brief(name, root=ROOT, base=BASE, worktree_root=WORKTREE_ROOT, session='<session>'):
    """The brief of a unit with no F-id (gitattr, census): the worktree and the digest, no queue row (F84 PR; three
    lanes on 03/11 had no brief because their unit was not in the queue)."""
    sections((root / CONTRACT).read_text(encoding='utf-8'))
    if not (root / DIGEST).is_file():
        raise BriefError(f'{DIGEST}: missing; run scripts/generate lane-digest')
    rules = (root / DIGEST).read_text(encoding='utf-8')
    worktree = f'{worktree_root.rstrip("/")}/{name}'
    out = [f'# Lane brief: {name} (no queue row)', '',
           f'Worktree: `{worktree}`, branch `units/{name}` from `origin/{base}`, with the toolchain linked: '
           f'`scripts/lane worktree {name}` (F81).',
           f'Session for the trailers: {session}', '',
           f'The unit is not in {QUEUE}: its scope is the task the coordinator handed over. Title the PR `{name}: ...`.', '',
           f'## Rules (digest of {CONTRACT}; read a numbered item there only when a step is unclear)', '']
    out.append(''.join(line for line in rules.splitlines(keepends=True) if not line.startswith('<!--'))
               .replace('<worktree>', worktree).replace('<fxx>', name)
               .replace('<Fxx>', name).replace('<session>', session))
    return '\n'.join(out).rstrip() + '\n'


def brief(unit, root=ROOT, base=BASE, worktree_root=WORKTREE_ROOT, session='<session>', run=subprocess.run,
          reds=base_reds):
    if not UNIT.match(unit.upper()):
        name = unit.lower()
        if not re.match(r'^[a-z0-9][a-z0-9._-]*$', name):
            raise BriefError(f'{unit}: a unit is F followed by its number, or a name of letters, digits, ".", "_", "-"')
        return named_brief(name, root=root, base=base, worktree_root=worktree_root, session=session)
    unit = unit.upper()
    header, rows = queue_rows((root / QUEUE).read_text(encoding='utf-8'))
    if unit not in rows:
        raise BriefError(f'{unit}: no row in the active table of {QUEUE}')
    row = rows[unit]
    sections((root / CONTRACT).read_text(encoding='utf-8'))  # the contract the digest shortens must still exist
    if not (root / DIGEST).is_file():
        raise BriefError(f'{DIGEST}: missing; run scripts/generate lane-digest')
    rules = (root / DIGEST).read_text(encoding='utf-8')
    worktree = f'{worktree_root.rstrip("/")}/{unit.lower()}'
    branch = f'units/{unit.lower()}'
    title = TAG.sub('', row[1]) if len(row) > 1 else unit
    out = [f'# Lane brief: {unit}, {title}', '',
           f'Worktree: `{worktree}`, branch `{branch}` from `origin/{base}`, with the toolchain linked: '
           f'`scripts/lane worktree {unit}`.',
           f'Session for the trailers: {session}', '',
           f'## The unit (row {unit} of {QUEUE})', '']
    for name, value in zip(header[1:], row[1:]):
        out.append(f'- **{name}:** {value}')
    open_deps = [u for u in depends_on(row) if u in rows and u != unit]
    if open_deps:
        out += ['', f'**Waits on:** {", ".join(open_deps)} (still in the queue); bring the base in after they '
                    'merge, before the commits that touch their files.']
    out += context(unit, row, rows, root, base, run)
    out += red_section(root, base, reds=reds)
    out += ['', f'Close: do not edit {QUEUE}; `deliver` records the closed {unit} row and the manager closes rows in a '
                'batch (`scripts/deliver --close-queue`).', '',
            f'## Rules (digest of {CONTRACT}; read a numbered item there only when a step is unclear)', '']
    out.append(''.join(line for line in rules.splitlines(keepends=True) if not line.startswith('<!--'))
               .replace('<worktree>', worktree).replace('<fxx>', unit.lower())
               .replace('<Fxx>', unit).replace('<session>', session))
    return '\n'.join(out).rstrip() + '\n'


def worktree_name(name):
    """The worktree's directory and branch suffix: a queue unit (F81 -> f81) or any other short name (F81)."""
    lowered = name.lower()
    if not NAME.match(lowered):
        raise BriefError(f'{name}: a worktree name is a queue unit (F81) or letters, digits, ".", "_" and "-"')
    return lowered


def worktree(unit, home=HOME_CHECKOUT, base=BASE, worktree_root=WORKTREE_ROOT, run=subprocess.run):
    """Create the unit's worktree from the base and link the home checkout's .toolchain into it, in one call.
    Without the link the delivery's gate fails its preflight with class `env` (missing toolchain), three lanes on 03/11.
    An existing worktree is refreshed instead (F81): the base is fetched and merged into it (never a rebase) and a
    missing link is restored. Returns the path and whether it was created."""
    name = worktree_name(unit)
    home = Path(home)
    path = Path(worktree_root) / name
    toolchain = home / '.toolchain'
    existing = path.exists() or path.is_symlink()
    if existing and not (path / '.git').is_file():
        raise BriefError(f'{path} already exists and is not a git worktree; nothing created')
    if not toolchain.exists():
        raise BriefError(f'{toolchain} is missing: the worktree would fail the gate preflight; nothing created')
    fetch = ['git', '-C', str(home), 'fetch', '-q', 'origin', base]
    if existing:
        steps = (fetch, ['git', '-C', str(path), 'merge', '-q', '--no-edit', f'origin/{base}'])
    else:
        steps = (fetch, ['git', '-C', str(home), 'worktree', 'add', '-q', '-b', f'units/{name}', str(path),
                         f'origin/{base}'])
    for argv in steps:
        done = run(argv, capture_output=True, text=True)
        if done.returncode != 0:
            if argv[3] == 'merge':
                run(['git', '-C', str(path), 'merge', '--abort'], capture_output=True, text=True)
            raise BriefError(f'{" ".join(argv[3:5])} failed: {(done.stderr or "").strip()[-300:]}')
    if not (path / '.toolchain').exists():
        (path / '.toolchain').symlink_to(toolchain)
    return path, not existing


def started(unit, path, base=BASE, session='<session>', root=None, run=subprocess.run, reds=base_reds):
    """What `scripts/lane worktree` prints (F81): the worktree line, the brief of a queue unit read from the new
    worktree (so it is the base's freshest), and the one line every later command starts with. One call replaces
    the fetch, worktree, link, brief and environment calls a lane made by hand."""
    name = worktree_name(unit)
    out = []
    try:  # a named unit (census) gets the digest-only brief
        out.append(brief(unit, root=Path(root or path), base=base, worktree_root=str(Path(path).parent),
                         session=session, run=run, reds=reds))
    except BriefError as exc:  # a unit with no queue row still gets its worktree
        out.append(f'(no brief: {exc})\n')
    out.append(f'Each command: `cd {path} && <command>`; the scripts source scripts/cloud/env.sh and find origin '
               f'themselves (`source scripts/cloud/env.sh` only for a bare toolchain binary). Branch units/{name}. '
               f'The worktree is already built from a fresh origin/<base>: no `git fetch`/`merge FETCH_HEAD` in the home checkout.\n')
    return ''.join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['collect']:  # F69: its own parser, in its own module
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import lane_collect
        return lane_collect.main(argv[1:])
    parser = argparse.ArgumentParser(prog='scripts/lane', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('brief', help='print the lane brief of one queue unit, or of a named unit with no row')
    p.add_argument('unit', help='the queue unit, e.g. F68, or a name with no queue row, e.g. gitattr (digest only)')
    p.add_argument('--base', default=BASE)
    p.add_argument('--worktree-root', default=WORKTREE_ROOT)
    p.add_argument('--session', default='<session>', help='the session URL the commit trailers carry')
    p.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    w = sub.add_parser('worktree', help="create the unit's worktree from the base, with the toolchain linked, and print "
                       'its brief (an existing worktree gets the base merged in)')
    w.add_argument('unit', help='the queue unit, e.g. F68, or another short name (census, f61-2)')
    w.add_argument('--base', default=BASE)
    w.add_argument('--session', default='<session>', help='the session URL the brief names for the trailers')
    w.add_argument('--no-brief', action='store_true', help='print only the worktree line')
    w.add_argument('--worktree-root', default=WORKTREE_ROOT)
    w.add_argument('--home', type=Path, default=HOME_CHECKOUT, help='the checkout that holds .toolchain')
    sub.add_parser('collect', add_help=False, help="close a delivered lane from its report: deliver's diary note once and "
                   'its quota ledger line (F69; scripts/lane collect --help)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'worktree':
            path, created = worktree(args.unit, home=args.home, base=args.base, worktree_root=args.worktree_root)
            print(f'{path} (branch units/{worktree_name(args.unit)}, .toolchain linked'
                  f'{"" if created else f", origin/{args.base} merged in"})')
            if not args.no_brief:
                sys.stdout.write(started(args.unit, path, base=args.base, session=args.session))
        else:
            sys.stdout.write(brief(args.unit, root=args.root, base=args.base,
                                   worktree_root=args.worktree_root, session=args.session))
    except (BriefError, OSError) as exc:
        print(f'lane: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
