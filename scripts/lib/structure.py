"""The machine half of the structure rites (docs/process/STRUCTURE.md A4, A5, B5, C4, C5), the literal
rules D-063 (the absolute exception list only shrinks) and D-064 (c) (a value of 2+ areas is born in the common catalog),
the premise register with the body's `Premises:` line (D-066), and the configuration registry of D-068 (config_check:
registry, engine literals; the generated types and the contracts are the generated drift and schema compat stages'),
the engine vendor check of D-069 item 7 (vendor_check: a vendor call from scripts/ outside its adapter), the unit
manifests of D-067 (unit_check: every production file belongs to exactly one unit), and the user-facing text check of
D-069 item 15 (text_check: x-text entries, and the pilot unit's visible strings).

scripts/structure-check runs the repository checks in the gate. ship-verify imports fit_review for the
PR body. Errors fail; warnings are printed and never fail.

GX-15 (B-11, D-070): two parts. The tree part (tree_part: every module that reads only the head, base and merge-base
trees) is reused when its content key matches (tree_key; structure.tree_cache_enabled). The metadata part (the PR body,
the PR over REST judged on the gated sha, the review, the threshold check) always runs (P-42). `--metadata` runs it
alone, after any push or comment, and with --pr publishes pr.checked v1; the gate runs it as the stage `pr metadata`
(gate-hooks/prereq.sh), and its `structure check` stage, told by OU_STRUCTURE_TREE_ONLY, runs the tree part only.
"""
import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import sys
import time
import python_source

import commit_check
import config
import budget_check
import census
import config_check
import literal_census
import hermetic_check
import test_orphans
import text_check
import threshold_check
import decision_premises
import defects
import effort
import gate_areas
import postmortem_check
import plan_tick
import premises
import repo_hygiene
import retired_products
import retired_vendors
import train_git
import train_ownership
import unit_check
import vendor_check
import visual_guard

ROOT = Path(__file__).resolve().parents[2]
LINK_DIRS = ('docs/domain', 'docs/process', 'docs/architecture', 'docs/capabilities')
SIZE_BUDGET = config.get('budgets.pr_changed_lines')  # D-008: changed lines without tests and generated files
NOT_COUNTED = re.compile(r'(^|/)(tests?|e2e|fixtures|__fixtures__)/|\.test\.|(^|/)pnpm-lock\.yaml$|\.snap$|-baseline\.json$|-baseline/[^/]+\.json$')
TRAILER = re.compile(r'^(Capability|Instances|Fit-Review|Claude-Session):[ \t]*(.*?)[ \t]*$', re.M)
REVIEWER = r'\(independent reviewer session, head ([0-9a-f]{7,40})\)'  # D-054: who reviewed, and which head
REVIEW_COMMENT = re.compile(r'^Independent fit review \(reviewer session, head ([0-9a-f]{7,40})\): (APPROVED|CHANGES_REQUESTED)\b')
NOT_REVIEWED = re.compile(r'^not reviewed \(\S[^:]*? \d{4}-\d{2}-\d{2}: \S[^)]*\)$')  # D-055: no review step
FIT_APPROVED = re.compile(rf'approved by \S.*? (?:\d{{4}}-\d{{2}}-\d{{2}} {REVIEWER}|{REVIEWER} \d{{4}}-\d{{2}}-\d{{2}})$')
REQUESTED = re.compile(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?(Z|[+-]\d{2}:?\d{2})$')
CONDITION_LINE = re.compile(r'^condition:[ \t]*(.*?)[ \t]*$', re.M)
CONDITION = re.compile(r'(before-start|before-merge|before-production) (open|met \d{4}-\d{2}-\d{2}) — (\S.*)')
STATUS_DAY = re.compile(r'(approved|done) (\d{4}-\d{2}-\d{2})\b')
TEST_PROOF = re.compile(r'\.test\.|`scripts/[\w./-]+`')
PENDING = re.compile(r'test pending|\bS\d{2}[a-z]?\b|PR #\d+', re.I)


def trailers(body):
    """The last value of each B5 trailer line in a PR body."""
    return {key: value for key, value in TRAILER.findall(body or '')}


def fit_review(body, root=None):
    """(errors, warnings) for a PR body against STRUCTURE.md B5. ship-verify refuses on any error.

    With a repository root, a named capability's open before-merge condition is an error too (A5, D-054).
    """
    found = trailers(body)
    errors, warnings = [], []
    capability = found.get('Capability', '')
    if root is not None and re.fullmatch(r'CAP-\d{3}', capability):
        for path in sorted((Path(root) / 'docs/capabilities').glob(f'{capability}-*.md')):
            errors += [f'{capability} has an open before-merge condition: {text} (STRUCTURE.md A5)'
                       for kind, state, text in conditions(path.read_text())[1] if kind == 'before-merge' and state == 'open']
    fit = found.get('Fit-Review', '')
    if fit == 'not structural' or NOT_REVIEWED.match(fit):
        pass
    elif fit.startswith('not reviewed'):
        errors.append('"Fit-Review: not reviewed" must say who decided, when and why: '
                      '"Fit-Review: not reviewed (<who> YYYY-MM-DD: <reason>)" (D-055)')
    elif not fit.startswith('approved'):
        errors.append('PR body has no "Fit-Review: approved by <owner> YYYY-MM-DD", "Fit-Review: not structural" or '
                      '"Fit-Review: not reviewed (<who> YYYY-MM-DD: <reason>)" line (STRUCTURE.md B5, D-055)')
    else:
        if not FIT_APPROVED.search(fit):
            errors.append('"Fit-Review: approved" must name the reviewer, the independent reviewer session and the head it '
                          'reviewed, and the date: "Fit-Review: approved by A Torre (independent reviewer session, head <sha>) '
                          'YYYY-MM-DD" (STRUCTURE.md B5, D-054)')
        if not re.fullmatch(r'CAP-\d{3}', found.get('Capability', '')):
            errors.append('structural PR body has no "Capability: CAP-NNN" line (STRUCTURE.md A5)')
        if not found.get('Instances'):
            errors.append('structural PR body has no "Instances:" line (STRUCTURE.md B5)')
    if not found.get('Claude-Session'):
        warnings.append('PR body has no "Claude-Session:" line (D-007)')
    return errors, warnings


def review_errors(body, head, comments):
    """D-054/D-055 (B5): an `approved` trailer needs the latest review of this exact head to approve it, and to name that
    head. Without a review step (D-055) no comment is needed, but a review that exists and requests changes refuses."""
    def same(sha):
        return len(sha) >= 7 and head.startswith(sha)
    verdicts = [match.group(2) for match in map(REVIEW_COMMENT.match, comments) if match and same(match.group(1))]
    errors = []
    claimed = trailers(body).get('Fit-Review', '').startswith('approved')
    if not verdicts and not claimed:
        return errors
    if not verdicts:
        errors.append(f'no "Independent fit review (reviewer session, head {head[:12]}…): APPROVED" comment for the PR head '
                      '(STRUCTURE.md B5, D-054)')
    elif verdicts[-1] != 'APPROVED':
        errors.append(f'the latest independent fit review of head {head[:12]} is {verdicts[-1]}')
    named = re.search(REVIEWER, trailers(body).get('Fit-Review', ''))
    if named and not same(named.group(1)):
        errors.append(f'Fit-Review names head {named.group(1)}, not the PR head {head[:12]}; a new head needs a new review')
    return errors


def fetch_review(number):
    """(body, head sha, comment bodies) through the selected forge."""
    import forge_events
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'structure', f'pr-{number}', consumer='scripts/lib/structure.py')
    repo = config.get('forge-events.repo')
    pull = port.change(repo, number)
    return pull.get('body') or '', pull['head'], [item['body'] for item in port.comments(repo, number)]


def header(text):
    """`key: value` lines before the first section, without trailing `# comments`."""
    fields = {}
    for line in text.split('\n## ', 1)[0].splitlines()[1:]:
        key, sep, value = line.partition(':')
        if sep and re.fullmatch(r'[a-z][a-z-]*', key.strip()):
            fields[key.strip()] = re.sub(r'\s+#.*$', '', value).strip()
    return fields


def parse_time(value):
    match = REQUESTED.fullmatch(value or '')
    if not match:
        return None
    y, mo, d, h, mi, zone = match.groups()
    offset = timedelta(0) if zone == 'Z' else (1 if zone[0] == '+' else -1) * timedelta(
        hours=int(zone[1:3]), minutes=int(zone[-2:]))
    return datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=timezone(offset))


def conditions(text):
    """(errors, [(kind, state, text)]) for the `condition:` lines of a capability header (STRUCTURE.md A5, D-054)."""
    errors, found = [], []
    for value in CONDITION_LINE.findall(text.split('\n## ', 1)[0]):
        match = CONDITION.fullmatch(value)
        if match:
            found.append(match.groups())
        else:
            errors.append(f'"condition: {value}" is not "condition: before-start|before-merge|before-production '
                          'open|met YYYY-MM-DD — <condition>"')
    return errors, found


def check_capabilities(root):
    errors, count = [], 0
    for path in sorted((root / 'docs/capabilities').glob('CAP-*.md')):
        count += 1
        name = path.relative_to(root).as_posix()
        fields = header(path.read_text())
        if not fields.get('requested'):
            errors.append(f'{name}: no "requested:" line (STRUCTURE.md A5; the D5 clock starts there)')
        elif parse_time(fields['requested']) is None:
            errors.append(f'{name}: "requested: {fields["requested"]}" is not YYYY-MM-DDTHH:MM±HH:MM')
        else:
            status = STATUS_DAY.match(fields.get('status', ''))
            requested = parse_time(fields['requested']).date()
            if status and date.fromisoformat(status.group(2)) < requested:
                errors.append(f'{name}: "status: {status.group(0)}" is before "requested: {fields["requested"]}"; '
                              'a capability is requested before it is approved (D-054)')
        bad, found = conditions(path.read_text())
        errors += [f'{name}: {error}' for error in bad]
        if fields.get('status', '').startswith('done'):
            errors += [f'{name}: is done with an open {kind} condition: {text}'
                       for kind, state, text in found if state == 'open']
        if fields.get('visual', 'no') == 'yes' and not fields.get('figma'):
            errors.append(f'{name}: "visual: yes" without a "figma:" node (D-006)')
    return errors, count


def decision_rows(text):
    for line in text.splitlines():
        if re.match(r'\|\s*D-\d{3}\s*\|', line):
            yield [cell.strip() for cell in line.strip().strip('|').split('|')]


def clock_errors(rows, now):
    """S2 (D-196): from structure.decision_clock_from on, a decision number is written once and its row's time is not
    later than `now` (an aware datetime). A row with a date and no time is compared by its day in the row's zone."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(config.get('structure.decision_clock_zone'))
    first, seen, errors = config.get('structure.decision_clock_from'), set(), []
    for cells in rows:
        ident = cells[0]
        if int(re.sub(r'\D', '', ident)) < first:
            continue
        if ident in seen:
            errors.append(f'DECISIONS.md {ident}: the number is written twice; take the next free one (scripts/decision-next --claim)')
        seen.add(ident)
        stamp = re.search(r'(?P<day>\d{4}-\d{2}-\d{2})(?: (?P<time>\d{2}:\d{2}))?', cells[1] if len(cells) > 1 else '')
        if not stamp:
            continue
        local = now.astimezone(zone)
        written = datetime.fromisoformat(f'{stamp['day']}T{stamp['time'] or "00:00"}').replace(tzinfo=zone)
        if (stamp['time'] and written > local) or written.date() > local.date():
            errors.append(f'DECISIONS.md {ident}: its time {stamp.group()} is later than the clock ({local:%Y-%m-%d %H:%M}); '
                          'stamp the row with the time scripts/decision-next --claim prints')
    return errors


def check_decisions(root, today, now=None):
    path = root / 'docs/domain/DECISIONS.md'
    if not path.is_file():
        return [], [], 0
    errors, warnings, count = [], [], 0
    rows = list(decision_rows(path.read_text()))
    errors += clock_errors(rows, now or datetime.now(timezone.utc))
    for cells in rows:
        count += 1
        if len(cells) != 6:
            errors.append(f'DECISIONS.md {cells[0]}: expected 6 columns (Id, Date, Decision, Invariant, Proof, Status)')
            continue
        ident, when, proof = cells[0], cells[1], cells[4]
        if not TEST_PROOF.search(proof) and not PENDING.search(proof):
            errors.append(f'DECISIONS.md {ident}: no linked proof (test) and no pending PR or "test pending" (rite C5)')
        day = re.search(r'\d{4}-\d{2}-\d{2}', when)
        if day and re.search('test pending', proof, re.I):
            age = (today - date.fromisoformat(day.group())).days
            if age > 7:
                warnings.append(f'DECISIONS.md {ident}: test pending for {age} days (rite C5, weekly report)')
    return errors, warnings, count


ABSOLUTE_BASELINE = 'scripts/lib/absolute-literals-baseline'  # D-064 (a): where scripts/generate census renders an area


def baseline_files(root, base=None):
    """The absolute exception list, {path: {value: count}}: every unit's census record and, until migrated, the old
    per-area files (scripts/lib/census.py, CENSO-NO-MANIFESTO), in the checkout or in `base`; None if it holds none."""
    try:
        return census.entries(root, census.BASELINE, base) or None
    except census.CensusError:
        return None


def check_absolute_baseline(root, base=None):
    """D-063, D-064 (a): the absolute exception list only shrinks, per census area and value. Against the base, no
    area allows a value more times in all its files together; a literal may move with its file inside its area, and a
    value removed from one area does not pay for the same value added to another."""
    after = baseline_files(root)
    before = baseline_files(root, base) if base else None
    if after is None or before is None:
        return []

    def totals(files):
        counts = {}
        for path, values in files.items():
            for value, count in values.items():
                key = (census_area(path), value)
                counts[key] = counts.get(key, 0) + count
        return counts

    before, after = totals(before), totals(after)
    return [f'{ABSOLUTE_BASELINE}/{area}.json: {value} allowed {before.get((area, value), 0)} times in {base}, {count} here; '
            f'the list only shrinks per area (D-063, D-064 a): read the value from a catalog'
            for (area, value), count in sorted(after.items()) if count > before.get((area, value), 0)]


SHARED_LITERALS = 'scripts/lib/shared-literals.json'
TRIVIAL_LITERALS = frozenset({'number "0"', 'number "1"', 'boolean "true"', 'string ""'})  # D-063: the remainder domain


def census_area(path):
    """The census area of a path (scripts/lib/census.py: the name of the folder that holds it)."""
    return census.area(path)


def shared_values(files):
    """Each non-trivial listed value present in two or more census areas, with its areas."""
    areas = {}
    for path, values in files.items():
        for value in values:
            areas.setdefault(value, set()).add(census_area(path))
    return {value: sorted(found) for value, found in areas.items() if len(found) > 1 and value not in TRIVIAL_LITERALS}


def check_shared_literals(root, base=None):
    """D-064 (c): a value present in two or more areas is born in the common catalog (a catalog entry of the census).
    The census list (equal to the census, D-063) shows every literal still written in a production file; one in 2+ areas fails
    unless the registered list names it with a documented reason. The registered list only shrinks against the base;
    an entry that no longer spans 2+ areas is a warning, so a front that fixes a value need not edit the list (D-064 a)."""
    files = baseline_files(root)
    if files is None:
        return [], []
    shared = shared_values(files)
    listed = root / SHARED_LITERALS
    data = json.loads(listed.read_text()) if listed.is_file() else {'reasons': {}, 'values': {}}
    reasons, registered = data.get('reasons', {}), data.get('values', {})
    errors = [f'{SHARED_LITERALS}: {value} names the unknown reason "{reason}"'
              for value, reason in sorted(registered.items()) if reason not in reasons]
    errors += [f'{value} is written in {len(areas)} areas ({", ".join(areas)}) and is not in the common catalog: '
               f'a value of 2+ areas is born in a common catalog (scripts/census add --catalog; D-064 c)'
               for value, areas in sorted(shared.items()) if value not in registered]
    if base:
        shown = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{SHARED_LITERALS}'], capture_output=True, text=True)
        before = json.loads(shown.stdout).get('values', {}) if shown.returncode == 0 else None
        if before is not None:
            errors += [f'{SHARED_LITERALS}: {value} is not registered in {base}; the list only shrinks (D-064 c): '
                       'put the value in the common catalog' for value in sorted(registered) if value not in before]
    warnings = [f'{SHARED_LITERALS}: {value} no longer spans 2+ areas; integration drops it (D-064 c)'
                for value in sorted(registered) if value not in shared]
    return errors, warnings


def slug(heading):
    text = re.sub(r'[`*_]|\[([^\]]*)\]\([^)]*\)', r'\1', heading.strip().lower())
    return re.sub(r'[^\w\- ]', '', text).replace(' ', '-')


def anchors(path, cache):
    if path not in cache:
        seen, found = {}, set()
        for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', strip_fences(path.read_text()), re.M):
            base = slug(heading)
            found.add(base if base not in seen else f'{base}-{seen[base]}')
            seen[base] = seen.get(base, 0) + 1
        cache[path] = found
    return cache[path]


def strip_fences(text):
    return re.sub(r'^```.*?^```', '', text, flags=re.M | re.S)


def check_links(root):
    errors, count, cache = [], 0, {}
    for folder in LINK_DIRS:
        for path in sorted((root / folder).glob('*.md')):
            text = re.sub(r'`[^`\n]*`', '', strip_fences(path.read_text()))
            for target in re.findall(r'\]\(([^)\s]+)\)', text):
                if re.match(r'[a-z][a-z0-9+.-]*:', target, re.I):
                    continue
                count += 1
                file_part, _, anchor = target.partition('#')
                resolved = (path.parent / file_part).resolve() if file_part else path
                where = f'{path.relative_to(root).as_posix()}: link {target}'
                if not resolved.exists():
                    errors.append(f'{where} does not resolve')
                elif anchor and resolved.suffix == '.md' and anchor not in anchors(resolved, cache):
                    errors.append(f'{where} names a missing heading')
    return errors, count


LITERAL_CATALOGS = 'scripts/lib/literal-catalogs'  # D-064 (a): one <area>.json manifest per census area


def catalog_files(root):
    """The catalog files the literal manifest declares: data, not code, so B5 leaves them out (D-064, amended)."""
    folder = root / LITERAL_CATALOGS
    if not folder.is_dir():
        return set()
    return {path for manifest in sorted(folder.glob('*.json')) for path in json.loads(manifest.read_text())['catalogs']}


def changed_lines(root, base):
    """Changed lines from base...HEAD without tests and generated files; None when git cannot tell."""
    result = subprocess.run(['git', '-C', str(root), 'diff', '--numstat', f'{base}...HEAD'], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    total = 0
    catalogs = catalog_files(root)
    for line in result.stdout.splitlines():
        added, removed, name = line.split('\t', 2)
        if added != '-' and not NOT_COUNTED.search(name) and name not in catalogs:
            total += int(added) + int(removed)
    return total


def changed_files(root, base):
    """Files of base...HEAD, or [] when there is no base or git cannot tell."""
    if not base:
        return []
    result = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', f'{base}...HEAD'], capture_output=True, text=True)
    return result.stdout.split() if result.returncode == 0 else []


def check_premises_line(root, body, changed):
    """D-066 (V0): (errors, warnings) of a PR body's `Premises:` line; the register's own errors are reported apart."""
    by_id, _ = premises.load(root)
    errors, warnings, _ = premises.check_line(body, by_id, changed)
    return errors, warnings


def plan_completeness_errors(body, commits):
    """GX-21: errors naming the plan items of the body that no real commit ticks. commits: [{message, files}]. A body
    without items is commit_check.plan_errors' to refuse; an empty commit ticks nothing (plan_tick.ticked_by_commits)."""
    missing = plan_tick.unticked(body, commits)
    if not missing:
        return []
    numbers = ', '.join(str(number) for number in missing)
    return [f'plan: item(s) {numbers} not ticked by a commit that changes a file (an empty commit ticks nothing); fix: edit the '
            f'PR body so the plan lists what the commits deliver, or add a REAL commit with the "Plan: N" trailer, never an empty one']


def plan_verdict(body, commits, draft):
    """D-083: (errors, warnings) of the plan completeness of a PR head. A draft's head is judged on what its commits
    delivered: an item not yet ticked is a warning, so a serial PR can be green on every commit while its plan is still a
    plan; a PR marked ready is refused as GX-21 says. pr.ready waits for every item either way (pr_ready, D-065 V4)."""
    missing = plan_completeness_errors(body, commits)
    if not draft:
        return missing, []
    return [], [f'{line} [draft PR: refused once it is marked ready; pr.ready waits for every item (D-083)]'
                for line in missing]


def lane_errors(root, merge_base, files):
    """GX-21: errors when the files touch the units of several lanes (the lane is undecidable and the train would refuse
    it), listing each unit with its lane. A change touching no unit, or only shared paths, has no lane and is fine; the
    rule is train_ownership's lanes(), the one lane_of() reads (LANE-OWN)."""
    touched = train_ownership.UnitOwnership(train_git.GitWorkspace(root)).lanes(merge_base, files, 'HEAD')  # D-112
    if len(set(touched.values())) <= 1:
        return []
    listed = ', '.join(f'{unit} ({lane})' for unit, lane in sorted(touched.items()))
    return [f'lane undecidable: the change touches units of several lanes: {listed}; split it into one PR per lane']


def gated_fetch(root, number, sha=None, observation=None):
    """commit-check's view of PR number judged on the gated sha (GX-14): sha, else this checkout's HEAD when it is a
    commit of the PR (the gate runs structure-check in its checkout of the gated sha), else the live head."""
    head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if observation is None:
        return commit_check.fetch(number, sha, root, head=head or None)
    return commit_check.fetch(number, sha, root, head=head or None, observation=observation)  # PR-OBSERVATION


def default_root():
    found = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return Path(found.stdout.strip()) if found.returncode == 0 else ROOT


TREE_ONLY_ENV = 'OU_STRUCTURE_TREE_ONLY'  # gate-hooks/prereq.sh names this tool root: the gate runs `pr metadata` apart
TREE_CACHE_ENV = 'STRUCTURE_TREE_CACHE_DIR'


def tree_part(root, base, today):
    """GX-15 (B-11): the modules that read only the checkout's tree and, for a diff, the base and merge-base trees.
    {errors, warnings, counts}. threshold_check is not here: it reads the PR body and commit messages (metadata)."""
    listed = commit_check.git(root, 'ls-files', '--', 'scripts') or ''
    paths = [Path(root) / name for name in listed.splitlines() if name.endswith('.py') and '/generated/' not in name]
    config_result, literal_result, unit_result, vendor_result, hermetic_result, hygiene_result = source_checks(root, base, paths)
    cap_errors, caps = check_capabilities(root)
    dec_errors, warnings, decisions = check_decisions(root, today)
    link_errors, links = check_links(root)
    errors = cap_errors + dec_errors + link_errors  # OU-DECOUPLE F5 (D-113): the Drizzle checks left with OU
    errors += check_absolute_baseline(root, base)
    errors += census.check(root, base)  # CENSO-NO-MANIFESTO: each unit's record, written only by scripts/census
    shared_errors, shared_warnings = check_shared_literals(root, base)
    errors += shared_errors
    warnings += shared_warnings
    config_errors, config_warnings = config_result
    errors += config_errors
    warnings += config_warnings
    budget_errors, budget_warnings = budget_check.check(root, base)  # D-069 item 14, D-025
    errors += budget_errors
    warnings += budget_warnings
    literal_errors, literal_warnings = literal_result  # LT1, D-069 item 3, D-025
    errors += literal_errors
    warnings += literal_warnings
    hermetic_errors, hermetic_warnings = hermetic_result
    errors += hermetic_errors
    warnings += hermetic_warnings
    errors += text_check.check(root)
    errors += test_orphans.check(root)  # TX25: every test_*.py is run by exactly one wrapper
    errors += gate_areas.coverage_errors(root)  # OU-DECOUPLE F1 (D-106): every tracked path has an area
    errors += repo_hygiene.tree_check(root) + hygiene_result[0]  # text is live; source diagnostics use exact inputs
    errors += retired_products.check(root)  # OU-DECOUPLE F5 (D-113): the engine names no retired product
    errors += retired_vendors.check(root)  # D-318: nothing of ours relates to a retired vendor
    # vazão F16 (D-292): the lockfile checks (toolchain_check, supply_chain_check) left; they judged zero packages.
    vendor_errors, vendor_warnings = vendor_result
    errors += vendor_errors
    warnings += vendor_warnings
    # D-322: the production guard (D-054, D-069 item 13) is its own gate stage, "production guard"; no import here.
    premise_errors, recorded = premises.check_register(root)
    errors += premise_errors
    errors += defects.check(root, base)[1]  # KD1: schema, audit chain, derived owner, append-only against the base
    errors += postmortem_check.check(root)  # D-069 item 9: every incident names its existing check and test
    decision_errors, decision_warnings = decision_premises.check(
        root, base, changed_files(root, base) if base else [])  # D-066, D-069 item 10
    errors += decision_errors
    warnings += decision_warnings
    unit_errors, unit_warnings = unit_result
    errors += unit_errors
    warnings += unit_warnings
    if base:
        size = changed_lines(root, base)
        if size is None:
            warnings.append(f'size: cannot diff {base}...HEAD; D-008 budget not measured')
        elif size > SIZE_BUDGET:
            warnings.append(f'size: {size} changed lines without tests and generated files (D-008 budget {SIZE_BUDGET})')
    counts = {'caps': caps, 'decisions': decisions, 'links': links, 'recorded': recorded}
    return {'errors': errors, 'warnings': warnings, 'counts': counts}


def _rev(root, *args):
    out = commit_check.git(root, *args)
    return out.strip() if out and out.strip() else None


def clean(checkout):
    """True when git holds every file of the checkout (no tracked change, no untracked file that is not ignored)."""
    return commit_check.git(checkout, 'status', '--porcelain', '--untracked-files=normal') == ''


def tool_state():
    """[scripts/ tree, config/ tree] of the tool root (this module's checkout), or None when it is dirty or not git."""
    if not clean(ROOT):
        return None
    parts = [_rev(ROOT, 'rev-parse', 'HEAD:scripts'), _rev(ROOT, 'rev-parse', 'HEAD:config')]
    return parts if all(parts) else None


def tree_key(root, base, today):
    """The tree part's content key, or '' when it must run: the cache is off, the checkout or the tool root has a
    change git does not hold (tracked or untracked), or a git read fails. The key covers the key version, the head,
    base and merge-base trees, the gate version (gate_pin.gate_version: the tool root's scripts/ tree), the tool root's
    registry tree and the config overrides, and the day (the C5 age check reads it)."""
    if not config.get('structure.tree_cache_enabled'):
        return ''
    try:
        tool = tool_state()
        if tool is None or not clean(root):
            return ''
        parts = [_rev(root, 'rev-parse', 'HEAD^{tree}'), *tool]
        if base:
            merge_base = _rev(root, 'merge-base', base, 'HEAD')
            parts += [_rev(root, 'rev-parse', f'{base}^{{tree}}'), merge_base and _rev(root, 'rev-parse', f'{merge_base}^{{tree}}')]
        if not all(parts):
            return ''
        overrides = json.dumps(config.overrides(), sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - a key that cannot be built means the modules run
        return ''
    material = ['structure-tree', config.get('structure.tree_cache_version'), base or '', today.isoformat(), overrides, *parts]
    return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()


def tree_store():
    from adapters import storage
    location = os.environ.get(TREE_CACHE_ENV) or os.path.expanduser(config.get('structure.tree_cache_dir'))
    return storage.open_store(location)


def source_analysis_inputs(root, files):
    """Contents read by the source checks, in addition to every tracked filename.

    All non-Markdown contents are conservatively included. Markdown is also included when a configured scanner,
    manifest, production-size/import analysis, vendor catalog or decision register reads its contents. Prose-only
    edits still run all remaining tree checks, including links and the unit intake/audit/plan checks.
    """
    registry = unit_check.units
    needed = set(registry.production(files, root)[0])
    needed.update(path for path, _ in config_check.engine_files(root, excludes=()))
    needed.update(path.relative_to(root).as_posix() for path in registry.manifest_files(root))
    needed.update(config.get(name, root) for name in (
        'units.manifest_schema', 'units.decision_register', 'providers.vendor_catalog', 'providers.vendor_catalog_schema'))
    needed.update(config.get('units.tsconfig_files', root))
    return {name for name in files if not name.endswith('.md') or name in needed}


def source_analysis_key(root, base):
    """Exact source-analysis inputs; unavailable/dirty inputs always run the checks."""
    if not base or not config.get('structure.tree_cache_enabled'):
        return ''
    try:
        tool = tool_state()
        if tool is None or not clean(root):
            return ''
        listed = commit_check.git(root, 'ls-tree', '-rz', 'HEAD')
        rows = [entry.split('\t', 1) for entry in listed.split('\0') if entry]
        files = [name for _, name in rows]
        needed = source_analysis_inputs(root, files)
        if any((Path(root) / name).is_symlink() for name in needed):
            return ''
        resolved_base = _rev(root, 'rev-parse', f'{base}^{{commit}}')
        if not resolved_base:
            return ''
        material = ['source-analysis', sys.version, config.get('structure.tree_cache_version'), *tool, resolved_base,
                    config.overrides(), config.overrides(root),
                    [(name, record if name in needed else '') for record, name in rows]]
        return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()
    except Exception:  # noqa: BLE001 - an incomplete input declaration is a miss, never a skipped check
        return ''


def source_checks(root, base, paths):
    """Reuse the source-only analysis across prose edits, with original diagnostics and live policy."""
    key = source_analysis_key(root, base)
    if key:
        try:
            held = json.loads(tree_store().get(f'source/{key}') or 'null')
            if (isinstance(held, dict) and held.get('key') == key and isinstance(held.get('result'), list)
                    and len(held['result']) == len(('config', 'literals', 'units', 'vendors', 'hermetic', 'hygiene'))
                    and all(isinstance(row, list) and len(row) == len(('errors', 'warnings'))
                            and all(isinstance(lines, list) and all(isinstance(line, str) for line in lines)
                                    for lines in row) for row in held['result'])):
                return held['result']
        except Exception:  # noqa: BLE001 - a malformed/unavailable diagnostic record is a miss
            pass
    result = python_source.checks(
        [(config_check.check, (root, base)), (literal_census.check, (root, base)),
         (unit_check.check, (root,)), (vendor_check.check, (root, base)),
         (hermetic_check.check, (root, base)), (repo_hygiene.source_check, (root,))], paths,
        config.get('structure.tree_workers'), config.get('structure.parallel_min_files'))
    if key:
        try:
            tree_store().put(f'source/{key}', json.dumps({'key': key, 'result': result}).encode())
        except Exception:  # noqa: BLE001 - loss of an optimization cannot change the diagnostics
            pass
    return result


def cached_tree_part(root, base, today, out=None):
    """Reuse immutable diagnostics, including errors, for exactly these inputs; never cache the policy verdict.
    main applies the current regime to these diagnostics on every call. An unreadable store only costs the run."""
    out = out or print
    began = time.monotonic()
    key = tree_key(root, base, today)
    if key:
        try:
            blob = tree_store().get(f'tree/{key}')
            held = json.loads(blob) if blob else None
        except Exception:  # noqa: BLE001
            held = None
        result = held.get('result') if isinstance(held, dict) and held.get('key') == key else None
        if (isinstance(result, dict) and isinstance(result.get('counts'), dict)
                and all(isinstance(result.get(field), list) and all(isinstance(line, str) for line in result[field])
                        for field in ('errors', 'warnings'))):
            out(f'structure tree: cached ({time.monotonic() - began:.2f} s, key {key})')
            return result
    with config.reading(), python_source.snapshot():
        result = tree_part(root, base, today)
    stored = ''
    if key:
        try:
            tree_store().put(f'tree/{key}', json.dumps({'key': key, 'result': result}, sort_keys=True).encode())
            stored = f', stored key {key}'
        except Exception:  # noqa: BLE001
            stored = ', not stored'
    out(f'structure tree: ran ({time.monotonic() - began:.2f} s{stored if key else ", no cache key"})')
    return result


def metadata_part(root, args):
    """GX-15 (B-11): what reads the PR rather than the tree: the body file, the PR over REST judged on the gated sha
    (GX-14), the review, and the threshold check (body and commit messages). Never cached (P-42). (errors, warnings, pr)."""
    errors, warnings = [], []
    if args.pr_body:
        body = args.pr_body.read_text()
        body_errors, body_warnings = fit_review(body, root)
        errors += body_errors + commit_check.plan_errors(body) + effort.body_errors(body, root)  # EFFORT-STEP
        warnings += body_warnings
        if args.base and not args.pr:
            try:
                errors += plan_completeness_errors(body, plan_tick.commits_with_files(args.base, root))
                merge_base = commit_check.git(root, 'merge-base', args.base, 'HEAD')
                if merge_base:
                    errors += lane_errors(root, merge_base.strip(), changed_files(root, args.base))
            except subprocess.CalledProcessError as error:
                warnings.append(f'plan: commits of {args.base}..HEAD not readable ({error.stderr.strip()})')
        line_errors, line_warnings = check_premises_line(root, body, changed_files(root, args.base))
        errors += line_errors
        warnings += line_warnings
        if args.base and not args.pr:
            branch = subprocess.run(['git', '-C', str(root), 'branch', '--show-current'], capture_output=True, text=True).stdout.strip()
            guard_errors, guard_warnings = visual_guard.check(root, args.base, body, changed_files(root, args.base), branch)
            errors += guard_errors
            warnings += guard_warnings
    fetched = None
    if args.pr:
        try:
            seen = getattr(args, 'observation', None)  # PR-OBSERVATION: what the live service read, not the forge
            observed = json.loads(seen.read_text()) if seen else None
            pr = gated_fetch(root, args.pr, args.sha, observation=observed)
        except (RuntimeError, OSError, KeyError) as error:  # any forge read error: blind, never liftable (GC)
            errors.append(Blind(f'commit-check: PR #{args.pr} not readable ({error})'))
        else:
            fetched = pr
            errors += commit_check.check(pr, commit_check.decisions(root))
            plan_errors, plan_warnings = plan_verdict(pr.get('body', ''), pr.get('commits', []), pr.get('draft', False))
            errors += plan_errors
            warnings += plan_warnings
            errors += effort.body_errors(pr.get('body', ''), root,  # EFFORT-STEP, D-069 items 4, 8, 9, D-025
                                          base=(pr.get('base') or {}).get('merge_base'),
                                          created=pr.get('created_at'))
            if (pr.get('base') or {}).get('merge_base'):
                errors += lane_errors(root, pr['base']['merge_base'], pr.get('files') or [])
            guard_errors, guard_warnings = visual_guard.check(root, args.base, pr.get('body', ''), pr.get('files') or [],
                                                              pr.get('branch'))  # D-006, SG1
            errors += guard_errors
            warnings += guard_warnings
            line_errors, line_warnings = check_premises_line(root, pr.get('body', ''), pr.get('files') or [])
            errors += line_errors
            warnings += line_warnings
    if args.review:
        try:
            body, head, comments = fetch_review(args.review)
        except (RuntimeError, OSError, KeyError) as error:
            errors.append(Blind(f'review: PR #{args.review} not readable ({error})'))
        else:
            body_errors, body_warnings = fit_review(body, root)
            errors += body_errors + review_errors(body, head, comments)
            warnings += body_warnings
    if args.base:
        # D-069 item 14, D-025: a registry threshold loosened against the base needs a cited decision
        if fetched:
            loosen_body, notes = fetched.get('body', ''), [commit['message'] for commit in fetched.get('commits', [])]
        else:
            loosen_body = args.pr_body.read_text() if args.pr_body else ''
            notes = threshold_check.messages(root, args.base)
        errors += threshold_check.check(root, args.base, loosen_body, notes)
        for envelope in threshold_check.report(root, args.base, args.pr, loosen_body):  # D-069 item 3: audit trail
            print('EVENT ' + json.dumps(envelope, sort_keys=True, separators=(',', ':')))
    return errors, warnings, fetched


def base_commit(root, base, pr):
    """The base commit the metadata was judged against: --base resolved in the checkout, else the PR base branch's
    remote-tracking ref, else the merge base GitHub reported."""
    candidates = [base] if base else []
    candidates.append(f'{config.get("push-guard.remote")}/{(pr.get("base") or {}).get("ref") or ""}')
    for ref in candidates:
        sha = _rev(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
        if sha:
            return sha
    return (pr.get('base') or {}).get('merge_base')


def publish_checked(root, number, pr, base, errors, port=None):
    """pr.checked v1 (EVENTS.md, GX-37) for the gated sha through the forge_events port: the PR-metadata verdict.
    Prints one line; a failure is printed and never changes the verdict. Returns the envelope or None."""
    try:
        import forge_events
        repo, sha = config.get('forge-events.repo'), pr['gated']['sha']
        if port is None:
            port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                            config.get('structure.event_producer'), f'pr-{number}')
        payload = dict(forge_events.subject(repo, number, sha, forge_events.premises_from_body(pr.get('body', ''))),
                       base_sha=base_commit(root, base, pr), result='fail' if errors else 'pass', errors=list(errors))
        envelope = port.emit('pr.checked', payload)
    except Exception as error:  # noqa: BLE001 - the event reports the verdict, it is never part of it
        print(f'pr.checked: not published ({type(error).__name__}: {error})')
        return None
    print(f'pr.checked: published #{number} {payload["result"]} sha={sha} base={payload["base_sha"]} event={envelope["event_id"]}')
    return envelope


def _lifted(lock):
    """regime.lifted(lock) (scripts/lib/regime.py): true while the exception regime holds and the lock is not kept (D-260).
    Without the module the regime cannot hold, so the lock stands as it does today."""
    try:
        import regime
    except ImportError:
        return False
    return regime.lifted(lock)


class Blind(str):
    """A refusal that says the forge could not be read (GC, D-260, D-300). The regime lifts rule debt, never blindness: a
    gate that could not read the PR judged nothing, so under_regime keeps this error whatever the regime holds."""


def under_regime(errors, warnings, lifted):
    """The refusals the exception regime lifts: each becomes a warning that names the lock, so nothing is silent (D-260).
    A Blind refusal (the PR or its review could not be read) is not rule debt and stays an error (fail closed, GC)."""
    kept = [line for line in errors if isinstance(line, Blind)]
    liftable = [line for line in errors if not isinstance(line, Blind)]
    if not lifted or not liftable:
        return errors, warnings
    return kept, warnings + [f'structure lock lifted by the exception regime: {line}' for line in liftable]


@config.reading()
def main(argv=None, port=None):
    parser = argparse.ArgumentParser(prog='scripts/structure-check', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, help='repository to check (default: the current checkout)')
    parser.add_argument('--today', type=date.fromisoformat, default=date.today(), help='YYYY-MM-DD for the C5 age check')
    parser.add_argument('--base', help='warn when base...HEAD exceeds the D-008 size budget')
    parser.add_argument('--pr-body', type=Path, help='check a PR body file for the B5 trailers and the D-022 commit plan')
    parser.add_argument('--pr', type=int, help='run commit-check (D-025) on this PR over GitHub REST, judged on this '
                        "checkout's HEAD when it is a PR commit (the gated sha), else the live head")
    parser.add_argument('--sha', help='--pr: the gated commit to judge instead')
    parser.add_argument('--review', type=int, metavar='PR',
                        help='before a merge: the B5 body check and the D-054 independent review of the PR head, over GitHub REST')
    parser.add_argument('--metadata', action='store_true',
                        help='only the PR-metadata part (the gate stage `pr metadata`; after any push or comment), never '
                        'cached; with --pr it publishes pr.checked v1')
    parser.add_argument('--no-publish', action='store_true', help='--metadata: publish no event (a report-only gate)')
    parser.add_argument('--observation', type=Path,
                        help='--metadata: judge what the live service read of the PR (GET /v1/pr-observation), not the forge')
    parser.add_argument('--snapshot', type=Path, help='--metadata: hand this run\'s fresh PR observation to its publisher')
    args = parser.parse_args(argv)
    root = (args.root or default_root()).resolve()
    tree_only = not args.metadata and os.environ.get(TREE_ONLY_ENV) == str(ROOT)
    errors, warnings, counts = [], [], None
    if not args.metadata:
        tree = cached_tree_part(root, args.base, args.today)
        errors, warnings, counts = list(tree['errors']), list(tree['warnings']), tree['counts']
    if not tree_only:
        meta_errors, meta_warnings, fetched = metadata_part(root, args)
        errors += meta_errors
        warnings += meta_warnings
        if args.metadata and args.pr and fetched is not None and args.snapshot:
            observed_base = base_commit(root, args.base, fetched)
            args.snapshot.write_text(json.dumps({'pr': args.pr, 'sha': fetched['gated']['sha'],
                                                 'change': {'head': fetched['gated']['live'], 'base': observed_base,
                                                            'body': fetched.get('body') or ''}}))
        if args.metadata and args.pr and fetched is not None and not args.no_publish:
            publish_checked(root, args.pr, fetched, args.base, meta_errors, port)
    errors, warnings = under_regime(errors, warnings, _lifted('structure'))
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    if counts is None:
        scope = f'PR #{args.pr}' if args.pr else 'no PR'
        print(f'structure-check (metadata, {scope}): {len(errors)} error(s), {len(warnings)} warning(s)')
    else:
        print(f'structure-check{" (tree)" if tree_only else ""}: {counts["caps"]} capability file(s), '
              f'{counts["decisions"]} decision(s), {counts["links"]} link(s); '
              f'{counts["recorded"]} premise(s); '
              f'{len(errors)} error(s), {len(warnings)} warning(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
