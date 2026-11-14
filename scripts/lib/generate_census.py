"""The census target of scripts/generate (CENSO-NO-MANIFESTO; D-063, D-064 a, D-069 item 1): the per-area view.

The literal catalogs and the absolute baseline were one committed file per census area that every unit with an entry
wrote, so N units of one area made N(N-1)/2 pairs that could collide on it. Each unit now keeps its own record,
units/<id>/census.jsonl (scripts/lib/census.py), and this renderer joins the records into the old per-area shapes,
`{description, catalogs}` and `{description, files}`, at the old paths. Nothing commits the join: it is printed, or
written under --out, and every reader builds the same view in memory, so no pull request can conflict on it.
"""
import json
from pathlib import Path

import census


def render(root, target):
    """{path: text} of every census area of both lists."""
    root = Path(root)
    files = {}
    for name in census.CENSUSES:
        folder, description = census.setting(f'{name}_legacy_dir', root), census.setting(f'{name}_view_description', root)
        for area, found in census.areas(root, name).items():
            document = {'description': description, census.LEGACY_KEYS[name]: found}
            files[f'{folder}/{area}.json'] = json.dumps(document, indent=1, ensure_ascii=False) + '\n'
    return files
