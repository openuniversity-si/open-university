"""The train writes what must stay in git (plan v3 U1, veto V4, P-10; docs/architecture/AGGREGATES.md).

No pull request commits an aggregate: each is a target of scripts/generate, a pure function of the unit manifests, the
cell files and the registry at one commit. When a snapshot of some of them has to live in git (a reader that cannot run
the generator), the train writes it, never a PR: after `integration.advanced` it renders the targets named by
train.published_aggregates from the new tip's tree and keeps one commit on train.aggregates_ref, a child of the tip
whose tree is the tip's tree plus those files. The commit is dated from its parent, so the same tip always gives the
same commit (replay, D-069 item 4). Off by default (train.publish_aggregates is an x-flag) and empty by default: today
every aggregate is read on demand. Publishing the ref to the forge is the forge port's job, not this module's.
"""
import os
from pathlib import Path
import subprocess
import tempfile

import generate


def checkout(workspace, commit, destination):
    """The commit's tree, unpacked into destination (git archive, no working-tree state involved)."""
    archive = subprocess.run(['git', '-C', str(workspace.root), 'archive', commit], capture_output=True,
                             timeout=workspace.timeout, check=True).stdout
    subprocess.run(['tar', '-x', '-C', str(destination)], input=archive, check=True, timeout=workspace.timeout)


def snapshot(workspace, tip, names):
    """The commit of the aggregates `names` rendered from the tree at `tip`, or None when there is nothing to keep
    (no name, or the tip already carries exactly those files)."""
    if not names:
        return None
    with tempfile.TemporaryDirectory() as scratch:
        unpacked = Path(scratch) / 'tree'
        unpacked.mkdir()
        checkout(workspace, tip, unpacked)
        declared = generate.targets(unpacked)
        unknown = [name for name in names if name not in declared]
        if unknown:
            raise generate.GenerateError(f'train.published_aggregates names unknown targets: {", ".join(unknown)}')
        files = {}
        for name in names:
            files.update(generate.expected(unpacked, name, declared[name]))
    env = dict(workspace.identity, GIT_INDEX_FILE=str(Path(tempfile.mkdtemp()) / 'index'))
    workspace.git('read-tree', tip, env=env)
    for path, text in sorted(files.items()):
        blob = subprocess.run(['git', '-C', str(workspace.root), 'hash-object', '-w', '--stdin'], input=text,
                              capture_output=True, text=True, check=True, timeout=workspace.timeout).stdout.strip()
        workspace.git('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}', env=env)
    tree = workspace.git('write-tree', env=env).stdout.strip()
    os.unlink(env['GIT_INDEX_FILE'])
    if tree == workspace.tree(tip):
        return None
    seconds = workspace.git('show', '-s', '--format=%ct', tip).stdout.strip()
    stamp = dict(workspace.identity, GIT_AUTHOR_DATE=f'{seconds} +0000', GIT_COMMITTER_DATE=f'{seconds} +0000')
    return workspace.git('commit-tree', tree, '-p', tip, '-m', f'train: aggregates of {tip[:8]}: {", ".join(names)}',
                         env=stamp).stdout.strip()
