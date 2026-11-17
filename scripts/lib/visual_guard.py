"""The protected-file and undeclared-visual-edit check (D-006, D-069 items 3 and 8; SG1), a module of scripts/structure-check.

check(root, base, body, files, branch) returns (errors, warnings) for one PR:
  protected  a PR whose head branch does not match structure.integration_branch_pattern changes none of
             structure.protected_files (the roadmap STATUS.md and the generated aggregates CONTEXTS.md, INTENTS.md);
  visual     a PR that changes a file under structure.visual_paths declares, with `Capability: CAP-NNN` in its body, a
             capability that is `visual: yes` and has a `figma:` node (D-006). Every change of a structure.always_visual_
             extensions file is visual; a .tsx change is visual only when one of its added or removed lines matches
             structure.markup_line_pattern, so a logic-only change passes. Test paths (structure.test_file_pattern) never count.
Without a PR (no changed files) nothing is judged.
"""
import json
from pathlib import Path
import re
import subprocess

import config
import units


def _header(text):
    fields = {}
    for line in text.split('\n## ', 1)[0].splitlines():
        key, sep, value = line.partition(':')
        if sep and re.fullmatch(r'[a-z][a-z-]*', key.strip()):
            fields[key.strip()] = value.strip()
    return fields


def protected(root, files, branch):
    if branch and re.search(config.get('structure.integration_branch_pattern', root), branch):
        return []
    listed = set(config.get('structure.protected_files', root))
    return [f'{path} is changed outside the integration flow (head branch {branch or "unknown"}); only a branch matching '
            'structure.integration_branch_pattern edits the step log and the generated aggregates (D-069 item 1)'
            for path in files if path in listed]


def _diff_lines(root, base, path):
    result = subprocess.run(['git', '-C', str(root), 'diff', '--unified=0', f'{base}...HEAD', '--', path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return [line[1:] for line in result.stdout.splitlines()
            if line[:1] in '+-' and not line.startswith(('+++', '---'))]


def _git(root, *args):
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ''


def _manifests_at(root, commit):
    """[(path, manifest)] of the unit manifests in the commit's tree, by path order (units.manifest_dir, manifest_file)."""
    pattern = f'{units.setting("manifest_dir", root)}/*/{units.setting("manifest_file", root)}'
    paths = sorted(path for path in _git(root, 'ls-tree', '-r', '--name-only', commit).splitlines()
                   if units.match(pattern, path))
    found = []
    for path in paths:
        try:
            found.append((path, json.loads(_git(root, 'show', f'{commit}:{path}'))))
        except ValueError:
            continue
    return found


def _retired(root, base, files):
    """D-112: the changed files gone from the head whose unit at the base the change retires (its manifest is gone too):
    removing a retired product renders nothing, so it is no visual edit. The units at the merge base are read from its
    tree with the units' own globs (D-322: no train module, a higher layer)."""
    gone = [path for path in files if not (Path(root) / path).exists()]
    if not base or not gone:
        return set()
    merge_base = _git(root, 'merge-base', base, 'HEAD').strip()
    if not merge_base:
        return set()
    manifests = _manifests_at(root, merge_base)
    at_head = set(_git(root, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines())
    retired = {manifest.get('id') for path, manifest in manifests if path in set(files) and path not in at_head}

    def owner(path):
        for _, manifest in manifests:
            if any(units.match(glob, path) for glob in manifest.get('paths', [])):
                return manifest.get('id')
        return None
    return {path for path in gone if owner(path) in retired - {None}}


def visual_files(root, base, files):
    """The changed files that are a visual change: (visual, unknown), `unknown` being .tsx files git could not diff."""
    globs = [units.compile_glob(glob) for glob in config.get('structure.visual_paths', root)]
    tests = re.compile(config.get('structure.test_file_pattern', root))
    always = tuple(config.get('structure.always_visual_extensions', root))
    markup = re.compile(config.get('structure.markup_line_pattern', root))
    visual, unknown = [], []
    retired = _retired(root, base, files)
    for path in files:
        if tests.search(path) or not any(glob.fullmatch(path) for glob in globs) or path in retired:
            continue
        if path.endswith(always):
            visual.append(path)
            continue
        lines = _diff_lines(root, base, path) if base else None
        if lines is None:
            unknown.append(path)
        elif any(markup.search(line) for line in lines):
            visual.append(path)
    return visual, unknown


def declared(root, body):
    """(ok, reason): whether the body's Capability is `visual: yes` with a `figma:` node."""
    match = re.search(r'^Capability:[ \t]*(CAP-\d{3})[ \t]*$', body or '', re.M)
    if not match:
        return False, 'the PR body has no "Capability: CAP-NNN" line'
    for path in sorted((Path(root) / 'docs/capabilities').glob(f'{match.group(1)}-*.md')):
        fields = _header(path.read_text())
        if fields.get('visual', 'no') != 'yes':
            return False, f'{match.group(1)} is not "visual: yes"'
        if not fields.get('figma'):
            return False, f'{match.group(1)} has no "figma:" node'
        return True, ''
    return False, f'{match.group(1)} has no file under docs/capabilities'


def check(root, base, body, files, branch):
    root = Path(root)
    if not files:
        return [], []
    errors = protected(root, files, branch)
    visual, unknown = visual_files(root, base, files)
    if visual:
        ok, reason = declared(root, body)
        if not ok:
            errors.append(f'visual change without a declared visual capability ({reason}; D-006): '
                          + ', '.join(visual[:5]) + (' ...' if len(visual) > 5 else '')
                          + '. Declare a capability with "visual: yes" and a "figma:" node, or keep the change to logic.')
    warnings = [f'{path}: cannot diff {base}...HEAD; visual change not judged' for path in unknown]
    return errors, warnings
