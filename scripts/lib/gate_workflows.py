"""The gate's `no GitHub Actions workflows` stage (ADR-24, amended by ADR-41 and D-086).

A file under .github/workflows or .github/actions is allowed only when gate.allowed_workflows names it: a hosted runner
is one optional, budgeted runner kind (D-087), staged under services/runner/github and installed by Daniel, never a
session (.claude/settings.json denies sessions that path). The list is the tool root's registry (the pinned gate's),
so a PR cannot allowlist its own workflow. The gate never reads a workflow's check: merging never depends on Actions.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

DIRECTORIES = ('.github/workflows', '.github/actions')


def found(root):
    """Every file under the GitHub Actions directories of `root`, as paths relative to it."""
    root = Path(root)
    return sorted(path.relative_to(root).as_posix() for directory in DIRECTORIES
                  for path in (root / directory).rglob('*') if path.is_file())


def refused(root, allowed=None):
    allowed = set(config.get('gate.allowed_workflows') if allowed is None else allowed)
    return [name for name in found(root) if name not in allowed]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    extra = refused(args[0] if args else '.')
    for name in extra:
        print(f'FAIL {name}: a GitHub Actions file gate.allowed_workflows does not name (ADR-24 as amended by ADR-41)')
    return 1 if extra else 0


if __name__ == '__main__':
    sys.exit(main())
