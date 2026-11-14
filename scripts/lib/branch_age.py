"""A branch older than process.branch_max_age_h is stale (D-069 item 11; plan v3.1 K1; P-32 events, never a clock).

The age of a branch is the time since the first event on its PR channel (its pr.opened, or the first event the port
holds for it). The rule is evaluated only when a trigger event (process.branch_trigger_types) is appended to that
channel: no cron, poll or sleep reads the clock (P-32). The caller passes `now` from the port's injected clock, so
the rule is deterministic and hermetic.

evaluate(events, trigger, now) returns the payload of branch.stale (contracts/events/branch.stale.v1.json) or None.
The port emits it with its deterministic id, so a branch is reported once per first event (its natural key).
"""
from datetime import datetime, timedelta

import config

SECONDS_PER_HOUR = 3600  # a unit conversion, not a tunable: the threshold is process.branch_max_age_h


def setting(name):
    return config.get(f'process.{name}')


def parse(stamp):
    """An RFC 3339 UTC instant as an aware datetime (the envelope's occurred_at)."""
    return datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def opened_at(events):
    """The earliest occurred_at of a channel's events, None when it holds none."""
    stamps = [event['occurred_at'] for event in events]
    return min(stamps, key=parse) if stamps else None


def age_hours(started, now):
    return (now - parse(started)).total_seconds() / SECONDS_PER_HOUR


def is_stale(started, now):
    """Strictly older than the threshold: a branch exactly at the limit is not yet stale."""
    return now - parse(started) > timedelta(hours=setting('branch_max_age_h'))


def is_trigger(event):
    """Whether this event needs branch history; decide before obtaining that history."""
    return event['type'] in setting('branch_trigger_types') and event['payload'].get('pr') is not None


def evaluate(events, trigger, now):
    """The branch.stale payload when the trigger's channel is stale, else None (P-32: only on a trigger event)."""
    if not is_trigger(trigger):
        return None
    started = opened_at(events)
    if started is None or not is_stale(started, now):
        return None
    payload = {key: trigger['payload'][key] for key in config.get('forge-events.subject_fields')}
    payload.update(opened_at=started, age_h=age_hours(started, now), max_age_h=setting('branch_max_age_h'))
    return payload
