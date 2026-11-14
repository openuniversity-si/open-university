"""The measured effect of a lesson (LR1, D-069 items 4 and 9): how often its class happened before and after it was applied.

A lesson lists `signals`: {event, stage, pattern}. One occurrence is one event of that type in the log that matches:
the stage (a `FAIL` stage of that name in a gate event) and the pattern (a regular expression found in a failing test id
or signature of the event). Events are read from the forge_events log, never from a clock: the window is lessons.effect_
window_days on each side of the lesson's applied.at. Too little data is `insufficient-data`, never a number.

  occurrences(signals, events)   the matching events with the time they cost (stage duration, ms)
  measure(lesson, events, now)   the effect block of the lesson record, or None when it was never applied
"""
from datetime import datetime, timedelta
import re

import config
import lessons


def setting(name):
    return config.get(f'lessons.{name}')


def parse_time(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def matches(signal, event):
    """The cost in ms of one occurrence of `signal` in `event`, or None when the event is not one."""
    if event.get('type') != signal['event']:
        return None
    payload = event.get('payload') or {}
    cost = 0
    if signal['stage']:
        stages = [s for s in payload.get('stages') or [] if s['name'] == signal['stage'] and s['result'] == setting('effect_stage_fail')]
        if not stages:
            return None
        cost = sum(s['duration_ms'] for s in stages)
    if signal['pattern']:
        pattern = re.compile(signal['pattern'])
        failing = [f'{t.get("id", "")} {t.get("signature", "")}' for t in payload.get('failing_tests') or []]
        if not any(pattern.search(text) for text in failing):
            return None
    return cost


def occurrences(signals, events):
    """[(occurred_at, cost_ms)] of the events that match any signal, once per event."""
    found = []
    for event in events:
        costs = [cost for cost in (matches(signal, event) for signal in signals) if cost is not None]
        if costs and event.get('occurred_at'):
            found.append((parse_time(event['occurred_at']), max(costs)))
    return found


def measure(lesson, events, now):
    """The effect block of a lesson: counts in the window before and after it was applied."""
    if not lesson.get('applied'):
        return None
    days = timedelta(days=setting('effect_window_days'))
    applied = parse_time(lesson['applied']['at'])
    verdicts = setting('effect_verdicts')
    found = occurrences(lesson['signals'], events)
    before = sum(1 for at, _ in found if applied - days <= at < applied)
    after = sum(1 for at, _ in found if applied <= at < applied + days)
    elapsed = now - applied >= days
    if not lesson['signals'] or not elapsed or before + after == 0:
        verdict = verdicts[3]
    else:
        verdict = verdicts[0] if after < before else verdicts[1] if after == before else verdicts[2]
    return {'measured_at': lessons.now_text(now), 'window_days': setting('effect_window_days'), 'before': before, 'after': after, 'verdict': verdict}
