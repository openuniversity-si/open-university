"""A hash-chained, append-only audit trail (D-069 items 3 and 4), parametrized by the digest and the genesis value.

One entry per line of <slug>.audit.jsonl, each carrying the digest of the one before it, so an edited or removed entry
breaks the chain. The caller passes the algorithm and the genesis digest from its own registry (lessons.*); nothing here
is a setting. The known-defect registry has its own copy of these functions (defects.py, KD1); moving it onto this
module is a separate change of that module's owner.
"""
import hashlib
import json


def entry_digest(entry, algorithm):
    body = {key: value for key, value in entry.items() if key != 'digest'}
    return hashlib.new(algorithm, json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def append_entry(trail, by, action, old, new, note, at, algorithm, genesis):
    """The trail with one more entry chained to the last."""
    prev = trail[-1]['digest'] if trail else genesis
    entry = {'n': len(trail) + 1, 'at': at, 'by': by, 'action': action, 'from': old, 'to': new, 'note': note, 'prev': prev}
    entry['digest'] = entry_digest(entry, algorithm)
    return trail + [entry]


def chain_errors(trail, name, algorithm, genesis):
    errors, prev = [], genesis
    for index, entry in enumerate(trail, 1):
        if entry.get('n') != index:
            errors.append(f'{name}: entry {index} is numbered {entry.get("n")}')
        if entry.get('prev') != prev:
            errors.append(f'{name}: entry {index} does not continue the chain (an entry was edited or removed)')
        if entry.get('digest') != entry_digest(entry, algorithm):
            errors.append(f'{name}: entry {index} was edited (its digest differs)')
        prev = entry.get('digest')
    return errors


def read_trail(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def dump_trail(trail):
    return ''.join(json.dumps(entry, sort_keys=True) + '\n' for entry in trail)
