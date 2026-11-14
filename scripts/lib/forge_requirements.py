"""Obligation and structural checks layered on operation_demands, never a second census.

Coordination (lock/unlock) remains on the forge adapter. calls is optional
accounting; moving either responsibility requires ARQ-ENGINE-COORDINATION.
"""
from dataclasses import dataclass

import operation_demands

JOURNAL = frozenset({'append', 'read'})
OPTIONAL = {'scripts/lib/train.py': frozenset({'calls'})}
CONDITIONAL = {'scripts/lib/train.py': {'approvals': 'foreign-ownership'}}


@dataclass(frozen=True)
class Requirements:
    required: frozenset
    conditional: tuple
    optional: frozenset
    journal: frozenset = JOURNAL

    def active(self, conditions=()):
        return self.required | frozenset(op for op, condition in self.conditional if condition in conditions)


def for_consumers(consumers, document=None):
    """Classify the existing declaration; all unclassified operations stay required."""
    document = operation_demands.load() if document is None else document
    required, conditional, optional = set(), {}, set()
    for consumer in consumers:
        for operation in document['consumers'].get(consumer, []):
            if operation in OPTIONAL.get(consumer, ()):
                optional.add(operation)
            elif operation in CONDITIONAL.get(consumer, {}):
                conditional[operation] = CONDITIONAL[consumer][operation]
            else:
                required.add(operation)
    return Requirements(frozenset(required), tuple(sorted(conditional.items())), frozenset(optional))


def responsible(adapter, operation):
    """Unwrap the forge route without attributing its missing method to the router."""
    # Import locally: forge_events imports this module during initialization.
    import forge_events
    while isinstance(adapter, forge_events.RoutingAdapter) and operation not in JOURNAL:
        adapter = adapter.main
    return adapter


def require_surface(adapter, operations, context):
    """Presence is necessary, never evidence of behavioral equivalence. No invocation."""
    for operation in sorted(operations):
        target = responsible(adapter, operation)
        if not callable(getattr(target, operation, None)):
            raise operation_demands.CompatibilityError(
                f'{context}: adapter {type(target).__name__} has no {operation} operation')
    return adapter


def require_coverage(consumers, covered, conditions=(), document=None):
    missing = for_consumers(consumers, document).active(conditions) - set(covered)
    if missing:
        raise operation_demands.CompatibilityError('contract lacks required operations: ' + ', '.join(sorted(missing)))
