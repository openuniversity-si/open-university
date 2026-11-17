"""Resolve the checkout whose code the gate evaluates."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def subject_root():
    """Code under test. The invoking checkout when OU_SUBJECT_ROOT is unset.

    gate-local points this at the PR-head worktree. ship-tail points its migration
    step at a worktree of that same head. Orchestration modules stay under ROOT.
    """
    raw = os.environ.get('OU_SUBJECT_ROOT', '').strip()
    if not raw:
        return ROOT
    path = Path(raw).resolve()
    if not path.is_dir():
        raise RuntimeError('OU_SUBJECT_ROOT is not a directory')
    return path

