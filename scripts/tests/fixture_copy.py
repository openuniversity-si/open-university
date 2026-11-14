"""Fixture copies that pay only for what a test reads (GATE-SPEED F2).

config/registry holds one aggregate per owner (`config/registry/<owner>.json`, the only files `config.get` reads) and,
since D-099, one source file per key under `config/registry/<owner>/`, which `scripts/generate registry` turns into the
aggregate: about 900 files, of which config reads about 60. Copying the whole folder for every test case cost about
240 ms of CPU against 4 ms for the aggregates, and every later `git add -A` of the fixture hashed the 900 files again.
A test that reads the configuration copies the aggregates; a test of the registry's own sources (the generator, the
merge of derived files) asks for them.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY = Path('config') / 'registry'


def registry(dest_root, sources=False, root=ROOT):
    """Copy `root`'s config/registry into `dest_root`: the aggregates config reads, and with `sources` every per-key
    source folder too. Returns the copied folder."""
    source, target = Path(root) / REGISTRY, Path(dest_root) / REGISTRY
    if sources:
        shutil.copytree(source, target, dirs_exist_ok=True)
        return target
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob('*.json')):
        shutil.copy2(path, target / path.name)
    return target


def folders(dest_root, relatives, root=ROOT):
    """Copy each folder of `relatives` from `root` into `dest_root` (existing folders merged), config/registry as its
    aggregates (`registry`)."""
    for relative in relatives:
        if Path(relative) == REGISTRY:
            registry(dest_root, root=root)
        else:
            shutil.copytree(Path(root) / relative, Path(dest_root) / relative, dirs_exist_ok=True)
