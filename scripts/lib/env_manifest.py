"""Check the engine's installed toolchain against its registered pins (D-027).

Open University and its package left in D-111. env-check keeps the toolchain probe;
package dependency audits, builds and automatic updates are retired (VAZÃO F13, D-292).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def toolchain_errors(root):
    """The pinned tools in root/.toolchain (or OU_TOOLCHAIN_DIR) answer the manifest versions."""
    import toolchain_manifest as manifest
    directory = manifest.toolchain_dir() if root == ROOT else root / '.toolchain'
    if not (directory / 'bin').is_dir():
        return [], [f'env: no toolchain in {directory}; run bash scripts/cloud/setup.sh']
    data = manifest.versions()
    errors = []
    for tool in manifest.TOOLS:
        try:
            seen = manifest.observed_version(tool, directory)
        except (OSError, RuntimeError, ValueError):
            seen = None
        if seen != data[tool]:
            errors.append(f'env: toolchain {tool} is {seen or "missing"}, registry {data[tool]}; '
                          'run bash scripts/cloud/setup.sh')
    return errors, []


def check(root=ROOT):
    """(errors, warnings) of env-check: the pinned toolchain is the engine's environment."""
    return toolchain_errors(root)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='scripts/env-check', description=__doc__.split('\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        errors, warnings = check(args.root.resolve())
    except (RuntimeError, OSError, ValueError) as error:
        errors, warnings = [f'env: {error}'], []
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    if errors:
        print(f'env-check: {len(errors)} problem(s). Run bash scripts/cloud/setup.sh; '
              'if the toolchain pins need changing, update the registry versions and their checksums in an env PR.')
        return 1
    print('env-check: environment matches the manifest')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
