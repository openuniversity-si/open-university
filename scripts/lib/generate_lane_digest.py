"""The lane-digest target of scripts/generate (VAZÃO F78): the lane rules digest a brief carries.

docs/process/lane.md keeps the digest of its delivery contract in its `## Rules digest` section, one ```digest block,
next to the contract it shortens. This target copies that block to docs/process/lane-digest.md, which
`scripts/lane brief` prints in place of the 4.8 KB contract. The target is committed, so `scripts/generate --check` (the
`generated drift` stage) refuses a digest that no longer matches lane.md; a digest over generate.lane_digest_max_bytes is refused outright.
"""
from pathlib import Path
import re

import config

SOURCE = 'docs/process/lane.md'
OUTPUT = 'docs/process/lane-digest.md'
HEADER = f'<!-- generated from {SOURCE} (Rules digest) -->\n'
BLOCK = re.compile(r'^## Rules digest\b.*?^```digest\n(.*?)^```', re.S | re.M)


class DigestError(ValueError):
    pass


def limit(root=None):
    """The most bytes the digest file may hold (generate.lane_digest_max_bytes, 1.5 KB)."""
    return config.get('generate.lane_digest_max_bytes', root)


def digest(text, most=None):
    """The digest file's text from lane.md's text."""
    most = limit() if most is None else most
    match = BLOCK.search(text)
    if match is None:
        raise DigestError(f'{SOURCE}: no ```digest block under `## Rules digest`')
    out = HEADER + match.group(1)
    size = len(out.encode('utf-8'))
    if size > most:
        raise DigestError(f'{SOURCE}: the rules digest is {size} bytes, over {most}')
    return out


def render(root, target):
    source = Path(root) / SOURCE
    if not source.is_file():
        return {}  # a fixture root without lane.md expects no digest
    return {OUTPUT: digest(source.read_text(encoding='utf-8'), limit(root))}
