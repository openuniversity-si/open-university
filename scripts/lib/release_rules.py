"""The production freeze and the release rule (D-054, docs/process/RELEASES.md; D-322): pure, read from one file.

scripts/release-policy.json is the only switch. While it says frozen, every write that would reach the real GitHub or
production host is refused. A loopback origin (the hermetic tests' fakes) is not production. A merge into the
production branch is refused unless its head is the release branch, frozen or not.

A layer-0 module (engine-events, beside the forge ports): the forge adapter that performs a merge (forge_origin)
judges it here without importing delivery; release_policy, delivery's command line, re-exports every name.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import config

POLICY = Path(__file__).resolve().parents[1] / 'release-policy.json'


class Refused(RuntimeError):
    """A production change the release policy does not allow."""


def load(path=POLICY):
    return json.loads(Path(path).read_text())


def loopback_origin(value):
    """http://127.0.0.1 or localhost only (release.loopback_hosts), never with credentials in the URL; '' otherwise."""
    if not value:
        return ''
    parts = urlsplit(value)
    if (parts.scheme == 'http' and parts.hostname in config.get('release.loopback_hosts')
            and not parts.username and not parts.password):
        return value.rstrip('/')
    return ''


def real(origin):
    """True unless origin is a loopback http fake, by the same rule the provider clients use."""
    return not loopback_origin(origin or '')


def refuse_frozen(action, origin, policy=None):
    """Raise Refused when production is frozen and origin is the real host."""
    policy = load() if policy is None else policy
    if policy['frozen'] and real(origin):
        raise Refused(f'{action} refused: production is frozen until {policy["until"]} ({policy["decision"]}, '
                      f'{policy["rules"]}); queue the change in {policy["queue"]}')


def refuse_merge(base, head, origin, policy=None, same_repository=True):
    """Raise Refused for a merge into the production branch that is not a release, or any while frozen.

    same_repository is False when the head branch lives in a fork: a fork's branch may carry the release name."""
    policy = load() if policy is None else policy
    if base != policy['production_branch']:
        return
    if head != policy['release_branch'] or not same_repository:
        raise Refused(f'merge into {base} refused: a release merges {policy["release_branch"]} of this repository, '
                      f'not {head}{"" if same_repository else " from a fork"} ({policy["decision"]}, {policy["rules"]})')
    refuse_frozen(f'merge into {base}', origin, policy)
