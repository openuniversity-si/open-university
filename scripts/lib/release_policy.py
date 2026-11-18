"""Production freeze and release unit (D-054, docs/process/RELEASES.md).

scripts/release-policy.json is the only switch. While it says frozen, every write that would reach the real GitHub or
production host is refused. A loopback origin (the hermetic tests' fakes) is not production. A
merge into the production branch is refused unless its head is the release branch, frozen or not. The rule itself is
release_rules (layer 0, D-322), re-exported here; this module keeps delivery's command line.
"""
import sys

# D-322: the rule is layer 0 (release_rules, engine-events); delivery's callers keep these names.
from release_rules import POLICY, Refused, load, loopback_origin, real, refuse_frozen, refuse_merge  # noqa: F401


def main(argv):
    """`production-branch`, `allowed-bases`, `closes-pattern`, `repository`: print the value (one cheap process, not the
    configuration CLI). A merge is judged in the forge adapter that performs it (refuse_merge), never by this CLI."""
    if argv == ['production-branch']:
        print(load()['production_branch'])
        return 0
    values = {'allowed-bases': 'delivery.merge_allowed_bases', 'closes-pattern': 'delivery.closes_pattern',
              'repository': 'forge-events.repo'}
    if len(argv) == 1 and argv[0] in values:
        import config  # only these need the registry; the policy file commands stay a cheap process
        value = config.get(values[argv[0]])
        print(' '.join(value) if isinstance(value, list) else value)
        return 0
    print('usage: release_policy.py production-branch | allowed-bases | closes-pattern | repository', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
