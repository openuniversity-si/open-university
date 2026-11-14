"""The model ladder port (D-069 item 7, plan v3.1 §4): which model a step runs on, as data in the registry.

providers.model_ladder lists the rungs from the least to the most capable model; each rung names its tier, the agent
provider that serves it, the model (the provider's id or alias) and the effort. A step asks for the rung of its tier.
After providers.model_escalate_after_failures real failures on one model it climbs providers.model_escalation_step
rungs; it never climbs down while the same PR runs, so a later request passes the model the PR already uses.
Failures counted here are the gate's code class (D-027): a flake or an env failure is not the model's.

CLI:  model_ladder.py list
      model_ladder.py pick --tier T [--current MODEL] [--failures N]
"""
import argparse
from collections import namedtuple
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

Rung = namedtuple('Rung', 'tier provider model effort use')
Choice = namedtuple('Choice', 'rung escalated reason')


class LadderError(ValueError):
    pass


class ModelLadder:
    def __init__(self, rungs, escalate_after, step):
        self.rungs = [Rung(**rung) for rung in rungs]
        self.escalate_after, self.step = escalate_after, step
        tiers = [rung.tier for rung in self.rungs]
        if not self.rungs or len(set(tiers)) != len(tiers):
            raise LadderError('providers.model_ladder needs at least one rung and one rung per tier')

    def index(self, *, tier=None, model=None):
        for position, rung in enumerate(self.rungs):
            if (tier is not None and rung.tier == tier) or (model is not None and rung.model == model):
                return position
        raise LadderError(f'no rung of providers.model_ladder has {"tier " + tier if tier else "model " + str(model)}')

    def rung(self, tier):
        return self.rungs[self.index(tier=tier)]

    def pick(self, tier, current=None, failures=0):
        """The rung a step of this tier runs on: never below the PR's current model, one escalation per threshold."""
        position = self.index(tier=tier)
        reason = f'tier {tier}'
        if current is not None and self.index(model=current) > position:
            position = self.index(model=current)
            reason = f'the PR already runs on {current}; never down mid-PR'
        escalated = failures >= self.escalate_after and position < len(self.rungs) - 1
        if escalated:
            position = min(position + self.step, len(self.rungs) - 1)
            reason = f'{failures} real failures on {current or self.rungs[self.index(tier=tier)].model}; one model up'
        return Choice(self.rungs[position], escalated, reason)


def from_config():
    return ModelLadder(config.get('providers.model_ladder'), config.get('providers.model_escalate_after_failures'),
                       config.get('providers.model_escalation_step'))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='model_ladder.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    pick = sub.add_parser('pick')
    pick.add_argument('--tier', required=True)
    pick.add_argument('--current')
    pick.add_argument('--failures', type=int, default=0)
    args = parser.parse_args(argv)
    ladder = from_config()
    try:
        if args.command == 'list':
            print(json.dumps([rung._asdict() for rung in ladder.rungs], indent=2))
        else:
            choice = ladder.pick(args.tier, args.current, args.failures)
            print(json.dumps(dict(choice.rung._asdict(), escalated=choice.escalated, reason=choice.reason)))
    except LadderError as error:
        print(f'model_ladder: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
