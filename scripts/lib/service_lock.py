"""Release a runner job's train lock through the forge port, including after KILL or restart (D-291).

The supervisor invokes this in a separate, time-bounded process: a forge call cannot hold the runner past its budget.
The port compares the owner, so cleanup never releases a successor's lock.
"""
import argparse

import config
import forge_events


def release(repo, owner, port=None):
    port = port or forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                          config.get('train.producer'), 'runner-cleanup')
    port.unlock(repo, config.get('train.lock_ref'), f'{config.get("train.producer")}@{owner}',
                died='runner cleanup after the job ended or restarted (D-291)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--owner', required=True)
    args = parser.parse_args()
    release(args.repo, args.owner)
