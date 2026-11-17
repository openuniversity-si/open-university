"""The ownership check of the unit manifests (D-067 (6), D-069 item 8), a module of scripts/structure-check.

check(root) returns (errors, warnings) for:
  manifests  every units/<id>/unit.json satisfies contracts/units/unit.v1.json, names a registered owner lane and
             cites a recorded decision for any budget override (scripts/lib/units.py);
  ownership  every production file (units.production_globs minus units.test_globs) belongs to exactly one unit, and
             no tracked file belongs to two. Two lanes therefore never edit the same file (P-13): this is D-064 (d)'s
             parallelism simulation turned into ownership by manifest. A companion (units.companions) belongs to its
             primary's unit; a claim of it by another unit is an error naming the manifest line to remove (TX21);
  stale      a manifest glob that matches no tracked file is a warning (the path moved or was deleted);
  requires   every static import between two units, measured by the same graph that seeded `requires` (scripts/lib/unit_map.py),
             follows a declared entry of the importing unit's `requires` (plan v3.1 U2): a new cross-unit import is a
             manifest change, which the owning lane makes; a `requires` naming no unit is an error, one nothing imports
             any more warns;
  oversize   a unit whose own production lines exceed its ceiling (units.budget: a cited override, else
             units.size_ceiling) is a warning while units.oversize_fails is false, an error once it flips (D-067 (7)).
The `@ou/<id>` address check left with Open University's TypeScript project, the only reader of the address map
(OU-DECOUPLE F4 (D-111)); a cross-unit import is still judged by `requires`.
A checkout without the manifest directory is not judged.
"""
import json
from pathlib import Path
import python_source
import subprocess

import config
import unit_map
import units


def tracked(root):
    listed = subprocess.run(['git', '-C', str(root), 'ls-files'], capture_output=True, text=True)
    return [path for path in (listed.stdout.split() if listed.returncode == 0 else []) if (Path(root) / path).is_file()]


def lines(root, path):
    try:
        data = (Path(root) / path).read_bytes()
    except OSError:
        return 0
    return 0 if b'\0' in data[:4096] else len(data.splitlines())


def claim_lines(root, unit, path):
    """['units/<id>/unit.json:<line> "<glob>"'] of each glob of the unit's manifest that matches the path."""
    manifest = Path(units.setting('manifest_dir', root)) / unit / units.setting('manifest_file', root)
    try:
        text = (Path(root) / manifest).read_text(encoding='utf-8').splitlines()
    except OSError:
        text = []
    found = []
    for glob in units.manifests(root)[unit]['paths']:
        if units.match(glob, path):
            spelled = f'"{glob}"'
            line = next((index for index, row in enumerate(text, 1) if spelled in row), None)
            found.append(f'{manifest.as_posix()}:{line} {spelled}' if line else f'{manifest.as_posix()} {spelled}')
    return found


def companion_errors(root, path, claims, derived):
    """The errors of a companion claimed by a unit other than its primary's (TX21): name the line to remove."""
    primary = units.primary_of(path, root)
    rule, _ = units.companion_rule(path, root)
    errors = []
    for unit in sorted(set(claims) - set(derived)):
        errors.append(f'{path} belongs to {", ".join(derived)}, the unit of {primary} (units.companions: '
                      f'{rule["companion"]} follows {rule["primary"]}); remove {" and ".join(claim_lines(root, unit, path))} '
                      f'(D-067 (6))')
    return errors


def siblings(path, owners):
    """The units that own the other files of the path's directory (the likely owner of an unowned file)."""
    folder = path.rpartition('/')[0]
    return sorted({unit for other, found in owners.items() if other != path and other.rpartition('/')[0] == folder
                   for unit in found})


def ownership(root, files=None):
    """(errors, warnings, owned production count) of the ownership rule over the tracked files."""
    files = tracked(root) if files is None else files
    patterns = units._cached(units._root(root))[1]
    claims = {path: [unit for unit, pattern in patterns.items() if pattern.fullmatch(path)] for path in files}
    owners, errors = {}, []
    for path in sorted(files):
        primary = units.primary_of(path, root)
        derived = sorted(units.claims_of(primary, root)) if primary else []
        if derived:
            errors += companion_errors(root, path, claims[path], derived)
            owners[path] = derived
        else:
            owners[path] = claims[path]
    for path, found in sorted(owners.items()):
        if len(found) > 1:
            where = [line for unit in sorted(found) for line in claim_lines(root, unit, path)]
            errors.append(f'{path} belongs to {len(found)} units ({", ".join(sorted(found))}); a file belongs to one unit '
                          f'(D-067 (6))' + (f'; claimed at {"; ".join(where)}' if where else ''))
    production, _ = units.production(files, root)
    for path in production:
        if not owners[path]:
            near = siblings(path, owners)
            hint = f'; the other files of its directory belong to {", ".join(near)}' if near else ''
            errors.append(f'{path} is a production file of no unit; add it to the manifest of the unit that owns it'
                          f'{hint} (D-067 (6))')
    warnings, present = [], set(files)
    for unit, manifest in sorted(units.manifests(root).items()):
        for glob in manifest['paths']:
            if '*' not in glob:
                if glob not in present:
                    warnings.append(f'units/{unit}: path {glob} matches no tracked file; remove or update it')
                continue
            pattern = units.compile_glob(glob)
            if not any(pattern.fullmatch(path) for path in files):
                warnings.append(f'units/{unit}: path {glob} matches no tracked file; remove or update it')
    return errors, warnings, sum(1 for path in production if len(owners[path]) == 1)


def oversize(root, files=None):
    """[(unit, production lines, ceiling)] of the units above their ceiling."""
    files = tracked(root) if files is None else files
    production, _ = units.production(files, root)
    exempt = units.matcher(units.setting('size_exempt_globs', root))
    counted = [path for path in production if not exempt.fullmatch(path)]
    found = []
    for unit, pattern in sorted(units._cached(units._root(root))[1].items()):
        size = sum(lines(root, path) for path in counted if pattern.fullmatch(path))
        ceiling = units.budget(unit, 'units.size_ceiling', root)
        if size > ceiling:
            found.append((unit, size, ceiling))
    return found


def dependencies(root, files=None):
    """(errors, warnings) of the declared `requires` against the measured import graph (D-067, plan v3.1 U2)."""
    code = unit_map.Code(root, tracked(root) if files is None else files, log='')
    # Dynamic selections are checked for declaration/targets, never promoted to requires (D-283).
    measured = unit_map.requires(root, code)
    manifests = units.manifests(root)
    errors, warnings = list(code.dynamic_errors), []
    for unit, manifest in sorted(manifests.items()):
        declared = set(manifest.get('requires', {}))
        for need in sorted(set(measured.get(unit, [])) - declared):
            errors.append(f'units/{unit}: imports unit {need} without declaring it; add "{need}": "^1" to its requires '
                          f'or drop the import (D-067, U2)')
        for need in sorted(declared - set(manifests)):
            errors.append(f'units/{unit}: requires unknown unit {need}')
        for need in sorted((declared & set(manifests)) - set(measured.get(unit, []))):
            warnings.append(f'units/{unit}: requires {need}, which it no longer imports; remove it')
    return errors, warnings


def fix_requires(root, files=None):
    """Rewrite each manifest's `requires` to the measured graph; returns the lines naming what changed.

    Adds `"<unit>": "^1"` for an import it does not declare, drops a declared unit it no longer imports; an unknown
    unit and every existing range stay as they are (the check still names the unknown one)."""
    root = Path(root)
    code = unit_map.Code(root, tracked(root) if files is None else files, log='')
    measured = unit_map.requires(root, code)
    known = units.manifests(root)
    changed = []
    for path in units.manifest_files(root):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        unit, declared = manifest['id'], manifest.get('requires', {})
        wanted = set(measured.get(unit, []))
        fixed = {need: version for need, version in declared.items() if need in wanted or need not in known}
        fixed.update({need: '^1' for need in wanted - set(fixed)})
        if fixed == declared:
            continue
        manifest.pop('requires', None)
        if fixed:
            manifest['requires'] = dict(sorted(fixed.items()))
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        changed.append(f'units/{unit}: requires +{sorted(set(fixed) - set(declared))} -{sorted(set(declared) - set(fixed))}')
    units.reset()
    return changed


def check(root):
    """(errors, warnings) of the manifests and the ownership rule; see the module docstring."""
    root = Path(root)
    try:
        folder = root / units.setting('manifest_dir', root)
    except config.ConfigError:
        return [], []  # a checkout without the units registry (a fixture of another check)
    if not folder.is_dir():
        return [], []
    errors = units.read(root)[1]
    if errors:
        return errors, []
    units.reset()
    files = tracked(root)
    owned_errors, warnings, _ = ownership(root, files)
    errors += owned_errors
    needed_errors, needed_warnings = dependencies(root, files)
    errors += needed_errors
    warnings += needed_warnings
    fails = units.setting('oversize_fails', root)
    for unit, size, ceiling in oversize(root, files):
        line = f'units/{unit}: {size} production lines above its ceiling of {ceiling} (unit.oversize; split it, D-067 (7))'
        (errors if fails else warnings).append(line)
    return errors, warnings


def operation_responsibility(document):
    """Findings for accepted operational attribution (D-285 R3), independent of paths.

    responsibility.accepted maps an operation to a list of explicit acceptances:
    {"responsible": "<person/role/lane>", "accepted_by": "<same accountable actor>",
     "evidence": "<decision or acceptance reference>"}. An edit records acceptance;
    this local check validates its shape, not the identity of the editor. The C2
    row's responsible is observational and never substitutes for acceptance.
    Keep competing records in the list: do not overwrite them in a keyed owner map.
    """
    accepted = document.get('responsibility', {}).get('accepted', {})
    if not isinstance(accepted, dict):
        return [('invalid-responsibility', 'responsibility.accepted must map operations to acceptance lists')]
    found = []
    for name in sorted(set(accepted) - set(document['operations'])):
        found.append(('unknown-responsibility', f'{name}: acceptance names no declared operation'))
    for name in document['operations']:
        records = accepted.get(name, [])
        if not isinstance(records, list):
            found.append(('invalid-responsibility', f'{name}: acceptance must be a list'))
            records = []
        owners = set()
        for record in records:
            owner = record.get('responsible') if isinstance(record, dict) else None
            if (not isinstance(owner, str) or not owner.strip() or owner.strip() == 'unknown'
                    or owner != owner.strip() or record.get('accepted_by') != owner
                    or not isinstance(record.get('evidence'), str) or not record['evidence'].strip()):
                found.append(('invalid-responsibility', f'{name}: acceptance needs responsible, matching accepted_by and evidence'))
                continue
            owners.add(owner)
        if not owners:
            found.append(('missing-responsibility', f'{name}: no accepted responsible'))
        elif len(owners) > 1:
            found.append(('conflicting-responsibility', f'{name}: competing accepted responsibles {sorted(owners)}'))
        observed = document['operations'][name].get('responsible')
        if owners and observed not in (None, '', 'unknown') and observed not in owners:
            found.append(('conflicting-responsibility', f'{name}: observed responsible {observed} disagrees with acceptance'))
    return found


@python_source.snapshot()
def operation_check(root, adapter, consumers=None):
    """One explicit refusing check of C2/C3/C4; never part of check(root).

    Findings and refusals are separate lists of (source, kind, detail). Missing
    acceptance, undeclared operations, invalid configuration boundaries and unmet
    adapter demands refuse. Observational drift and explicit unknowns stay visible.
    Each reader runs independently, including when another declaration is broken.
    Adapter and consumer scope are explicit; this does not select an adapter.
    """
    import operation_relations
    import operation_config
    import operation_demands
    import operation_demands_check

    root = Path(root)
    findings, refused = [], []

    def collect(source, rows, refusing):
        for kind, detail in rows:
            row = (source, kind, detail)
            findings.append(row)
            if kind in refusing:
                refused.append(row)

    try:
        document = operation_relations.load(root)
        rows = operation_responsibility(document)
        collect('relation', rows, {kind for kind, _ in rows})
        collect('relation', operation_relations.confront(root), {'undeclared-operation'})
    except (operation_relations.RelationError, TypeError, AttributeError) as error:
        collect('relation', [('invalid-declaration', str(error))], {'invalid-declaration'})
    try:
        collect('configuration', operation_config.confront(root),
                {'orphan-key', 'kind-conflict', 'implicit-sharing', 'false-sharing', 'unknown-operation'})
    except (operation_config.RelationError, operation_relations.RelationError) as error:
        collect('configuration', [('invalid-declaration', str(error))], {'invalid-declaration'})
    try:
        document = operation_demands.load(root)
        collect('compatibility', operation_demands_check.confront(root),
                {'undeclared-demand', 'unimplemented-proof', 'unknown-proof'})
        scope = list(document['consumers']) if consumers is None else list(consumers)
        collect('compatibility', [('unknown-consumer', name) for name in scope
                                 if name not in document['consumers']], {'unknown-consumer'})
        collect('compatibility', [('unproven-demand', f'{adapter}: {consumer}: {operation}')
                                 for consumer, operation in operation_demands.refusals(
                                     adapter, scope, document, root)], {'unproven-demand'})
    except (operation_demands.CompatibilityError, operation_relations.RelationError) as error:
        collect('compatibility', [('invalid-declaration', str(error))], {'invalid-declaration'})
    return findings, refused


def main(argv=None):
    """Opt-in operation validation; existing path ownership checks keep their contract."""
    import argparse
    from collections import Counter
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--operations', action='store_true', required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent.parent)
    parser.add_argument('--adapter', required=True)
    parser.add_argument('--consumer', action='append')
    args = parser.parse_args(argv)
    findings, refused = operation_check(args.root, args.adapter, args.consumer)
    for source in ('relation', 'configuration', 'compatibility'):
        counts = Counter(kind for origin, kind, _ in findings if origin == source)
        print(f'{source}: {sum(counts.values())} finding(s); {dict(sorted(counts.items()))}')
    for row in findings:
        print(('REFUSE' if row in refused else 'EXPOSE') + ': ' + ': '.join(row))
    print(f'operation-check: {len(findings)} finding(s), {len(refused)} refusal(s)')
    return int(bool(refused))


if __name__ == '__main__':
    raise SystemExit(main())
