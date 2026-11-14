"""The exception regime's lifted locks (D-260): every `lock.lifted` event since the regime began, as lock, sha, lane and time.

A lifted lock never refuses; the regime keeps its record here, so `gate-noite` lists every one of them and the exit of
the regime reviews the list. The events are the envelopes of the forge events port (`type`, `occurred_at`, `payload`).
"""
from datetime import datetime

KIND = 'lock.lifted'


def moment(text):
    """An RFC 3339 instant (`Z` or an offset) as an aware datetime, so two instants compare by time, not by text."""
    return datetime.fromisoformat(str(text).replace('Z', '+00:00'))


def lifted(events, since=None):
    """The lock.lifted events at or after `since` (an instant, or None for all), as rows in log order."""
    cut = moment(since) if since else None
    rows = []
    for event in events:
        if event.get('type') != KIND:
            continue
        when = event.get('occurred_at', '')
        if cut is not None and moment(when) < cut:
            continue
        payload = event.get('payload') or {}
        rows.append({'lock': payload.get('lock', '?'), 'sha': payload.get('sha', '?'), 'lane': payload.get('lane', '?'),
                     'time': when})
    return sorted(rows, key=lambda row: moment(row['time']))


def render(rows, since=None):
    """The listing as Markdown lines: a count, then one row per lifted lock (none says so)."""
    head = f'Locks lifted by the exception regime since {since or "its start"}: {len(rows)}'
    if not rows:
        return [head, '(none)']
    table = ['| lock | sha | lane | time |', '|---|---|---|---|']
    table += [f'| {row["lock"]} | {row["sha"]} | {row["lane"]} | {row["time"]} |' for row in rows]
    return [head, *table]
