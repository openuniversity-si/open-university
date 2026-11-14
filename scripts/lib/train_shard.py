"""The shard key of a change, and the shadow report of a batch (SH-1, GX-34;
docs/programs/gate-excellence/design-sharded-tier2.md 4.1 and 8).

key(manifests, files, generated) is a pure function: the units the files touch, plus every unit that `requires` one
of them (transitively), plus every file no unit claims that is not the output of a generate target. A key is a sorted
list of `unit:<id>` and `path:<file>` strings. Nothing here reads the forge or git; announce() is the one place that
does, through the workspace the train already has, and it only measures: the verdict and the merge never read it.

Two members whose keys share an element would have to wait for each other in a sharded tier 2; the shards a batch
would form are the connected groups of members over shared elements; collisions() names the shared elements and the
files that put them in each key.
"""
import engine_role
from gate_areas import glob_match
import train_ownership

KEYS = ('units+dependents',)


class ShardError(ValueError):
    pass


def check_mode(mode):
    """train.shard_key must be a value this module implements; anything else is an error, never a fallback."""
    if mode not in KEYS:
        raise ShardError(f'train.shard_key {mode!r} is not understood (only {", ".join(KEYS)})')
    return mode


def generated_globs(targets):
    """Globs of the files scripts/generate writes: the output of every enabled committed target, a file or a folder."""
    return [glob for target in targets if target.get('enabled') and target.get('committed')
            for glob in (target['output'], target['output'].rstrip('/') + '/**')]


def dependents(manifests):
    """{unit: units that require it, directly}."""
    found = {}
    for manifest in manifests:
        for required in manifest.get('requires', {}):
            found.setdefault(required, set()).add(manifest['id'])
    return found


def causes(manifests, files, generated=()):
    """{key element: the files that put it in the key}; a dependent unit is caused by the files of the unit it follows."""
    below, caused = dependents(manifests), {}
    for file in files:
        if any(glob_match(file, glob) for glob in generated):
            continue
        claimed = [manifest['id'] for manifest in manifests
                   if any(glob_match(file, glob) for glob in manifest.get('paths', []))]
        if not claimed:
            caused.setdefault(f'path:{file}', set()).add(file)
        pending, seen = list(claimed), set()
        while pending:
            unit = pending.pop()
            if unit not in seen:
                seen.add(unit)
                caused.setdefault(f'unit:{unit}', set()).add(file)
                pending.extend(below.get(unit, ()))
    return caused


def key(manifests, files, generated=()):
    return sorted(causes(manifests, files, generated))


def collisions(member_files, manifests, generated=()):
    """[{prs, key, files}] for every pair of members (by pr number) whose keys share an element."""
    caused = {pr: causes(manifests, files, generated) for pr, files in member_files.items()}
    found = []
    for index, first in enumerate(sorted(caused)):
        for second in sorted(caused)[index + 1:]:
            shared = sorted(set(caused[first]) & set(caused[second]))
            if shared:
                files = sorted({file for pr in (first, second) for element in shared for file in caused[pr][element]})
                found.append({'prs': [first, second], 'key': shared, 'files': files})
    return found


def shards(member_keys):
    """[{key, prs}]: the groups of members connected by a shared element, in order of their first member."""
    groups = []
    for pr in member_keys:
        elements = set(member_keys[pr])
        joined = [group for group in groups if group['key'] & elements]
        merged = {'key': set(elements), 'prs': [pr]}
        for group in joined:
            merged['key'] |= group['key']
            merged['prs'] += group['prs']
            groups.remove(group)
        groups.append(merged)
    return [{'key': sorted(group['key']), 'prs': sorted(group['prs'])}
            for group in sorted(groups, key=lambda group: min(group['prs']))]


def report(manifests, member_files, generated=()):
    """The payload fields of train.batch.shards for members {pr: files changed against the batch base}."""
    keys = {pr: key(manifests, files, generated) for pr, files in member_files.items()}
    union = key(manifests, sorted({file for files in member_files.values() for file in files}), generated)
    return {'members': [{'pr': pr, 'key': keys[pr]} for pr in sorted(keys)], 'union_key': union,
            'shards': shards(keys), 'collisions': collisions(member_files, manifests, generated)}


def announce(workspace, port, subject, bid, base, members):
    """Emit train.batch.shards for a started batch; nothing when train.shard_shadow is off.

    A shadow that cannot be measured (manifests unreadable) is printed and skipped: it must never change the verdict.
    """
    if not engine_role.setting('train.shard_shadow'):
        return
    mode = check_mode(engine_role.setting('train.shard_key'))
    try:
        manifests = train_ownership.UnitOwnership(workspace).manifests(base)
        generated = generated_globs(engine_role.setting('generate.targets'))
        found = report(manifests, {entry.pr: workspace.changed_files(base, entry.sha) for entry in members}, generated)
    except Exception as error:  # noqa: BLE001 - measurement only, see the docstring
        print(f'train: shard shadow skipped for {bid}: {error}')
        return
    try:
        port.emit('train.batch.shards', dict(subject, batch_id=bid, base_sha=base, shard_key=mode, **found))
    except Exception as error:  # noqa: BLE001 - measurement only: a shadow too large for one comment never stops the train
        print(f'train: shard shadow not published for {bid}: {error}')
