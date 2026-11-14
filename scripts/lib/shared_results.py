"""GATE-SPEED F10 (D-130): the script tests' results, shared between boxes by their input key.

A script test's key (gate_test_cache.key) is a digest of everything it reads: its covers' contents, the pinned
toolchain, the gate's key parts. A PASS of that key on one box is a PASS on any box, so a box that starts empty (a
fresh container, the e2-micro runner) need not run a test whose inputs some box already judged. The results live on
the forge as one log ref (gate.shared_results_ref), moved forward only over git (forge_git_ref: the egress proxy
permits nothing else); its tip holds every PASS still inside gate.test_cache_ttl_s as one record, so a run reads it
with one fetch and publishes the PASSes it adds with one push.

A run uses it only when OU_SHARED_RESULTS is 1 (scripts/test-suite and the gate set it; a script test never sees it,
gate.test_env_scrub_names). A box that cannot read the ref judges alone: an unreadable ref is no result, never a PASS.
"""
import os
import subprocess
import sys

import config
import forge_git_ref

ENV = 'OU_SHARED_RESULTS'


def enabled(environ=None):
    return (os.environ if environ is None else environ).get(ENV) == '1'


def valid(marker, key_value, now, ttl):
    """The marker when it is a PASS record of exactly this key, recorded within ttl seconds of now, else None."""
    try:
        stored_at = marker['stored_at']
        good = (marker['key'] == key_value and isinstance(stored_at, int) and not isinstance(stored_at, bool)
                and isinstance(marker['source'], str) and 0 <= now - stored_at <= ttl)
    except (KeyError, TypeError):
        return None
    return marker if good else None


class SharedResults:
    """The shared log of PASS records on one git remote."""

    def __init__(self, root, refs=None):
        self.refs = refs or forge_git_ref.GitRefs(root)
        self.name = config.get('gate.shared_results_ref')

    def read(self):
        """{key: marker} the ref's tip holds; {} when there is none or it cannot be read."""
        try:
            held = self.refs.read(self.name)
        except (forge_git_ref.GitRefError, OSError, subprocess.SubprocessError):
            return {}
        passed = held[1].get('passed') if held and isinstance(held[1], dict) else None
        return dict(passed) if isinstance(passed, dict) else {}

    def publish(self, held, added, now):
        """Append one record: the PASSes read and the ones this run added, those older than the cache's ttl dropped.
        True when it was pushed; a race lost every attempt, or a refused transport, is False (the run's verdicts stand;
        the next run publishes again)."""
        if not added:
            return False
        ttl = config.get('gate.test_cache_ttl_s')
        merged = {key: marker for key, marker in {**held, **added}.items() if valid(marker, key, now, ttl)}
        try:
            return self.refs.append(self.name, {'passed': merged}, config.get('gate.shared_results_attempts')) is not None
        except (forge_git_ref.GitRefError, OSError, subprocess.SubprocessError) as error:
            # the run's verdicts stand, but a silent failure hid this for hours (G2): say it once on stderr
            print(f'shared results: not published ({type(error).__name__}: {" ".join(str(error).split())})', file=sys.stderr)
            return False
