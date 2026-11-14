"""The one `FAIL env: <premise>` line of a test whose machine premise does not hold (TX12, D-070)."""
import sys


class MachinePremise(Exception):
    """A machine premise of a test does not hold. Deliberately not an assertion failure: the gate classifies the
    `FAIL env: <premise>` line env (scripts/lib/gate_classify.py), never the PR's code."""


def premise_failed(premise):
    """Print the one classified line and return the error to raise."""
    print(f'FAIL env: {premise}', file=sys.stderr, flush=True)
    return MachinePremise(premise)
