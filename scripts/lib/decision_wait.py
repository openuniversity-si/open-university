"""Owner waits in PR comments (X1): DECIDE, THEN REPORT (Daniel 2026-10-26 21:29).

No session may stop and wait for an owner decision. A comment line that holds one of push-guard.owner_wait_phrases
waits on the owner; a later line that starts with push-guard.decision_marker (in the same comment or a later one)
records the decision the session took and clears it. Lines in code fences, quoted lines ('>') and inline code spans
are not read, and comments of the forge_events log (forge-events.event_comment_marker) are skipped. Matching is
case-insensitive; a phrase that ends in ':' counts only at the start of a line (after list, heading or bold marks).

waiting(bodies) is shared by commit-check (the gate refusal) and stall-report (the owner_wait stall). before() keeps the
comments a gate may judge: those created up to the push of the gated head (GX-14), so a comment posted while the gate
runs never changes that gate's verdict.
"""
from datetime import datetime
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

CODE_SPAN = re.compile(r'`[^`]*`')
LEAD = ' \t-*+#_'
FENCE = '```'


def lines(body):
    """The readable lines of a comment: no fences, no quotes, no inline code, leading list/heading marks removed."""
    inside = False
    for raw in (body or '').splitlines():
        stripped = raw.strip()
        if stripped.startswith(FENCE):
            inside = not inside
            continue
        if inside or stripped.startswith('>'):
            continue
        yield CODE_SPAN.sub('', stripped).lstrip(LEAD)


def phrase_in(line, phrases):
    folded = line.casefold()
    for phrase in phrases:
        wanted = phrase.casefold()
        if (folded.startswith(wanted) if phrase.endswith(':') else wanted in folded):
            return phrase
    return None


def moment(value):
    """An RFC 3339 time as an aware datetime, else None."""
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def before(comments, cutoff=None):
    """The bodies of the comments created at or before cutoff (the gated head's push time). A plain body, a comment
    without a readable time and a missing cutoff are kept: only a comment known to be later than the push is dropped."""
    limit = moment(cutoff) if cutoff else None
    bodies = []
    for comment in comments:
        if not isinstance(comment, dict):
            bodies.append(comment)
            continue
        created = moment(comment.get('created_at')) if comment.get('created_at') else None
        if limit is None or created is None or created <= limit:
            bodies.append(comment.get('body') or '')
    return bodies


def waiting(bodies, root=None):
    """(comment index, phrase, line) of the owner wait no later Decision line clears, else None."""
    phrases = config.get('push-guard.owner_wait_phrases', root)
    marker = config.get('push-guard.decision_marker', root).casefold()
    events = config.get('forge-events.event_comment_marker', root)
    found = None
    for index, body in enumerate(bodies):
        if (body or '').startswith(events):
            continue
        for line in lines(body):
            if line.casefold().startswith(marker):
                found = None
            else:
                phrase = phrase_in(line, phrases)
                if phrase:
                    found = (index, phrase, line)
    return found


def errors(bodies, number=None, root=None):
    """The commit-check refusal of a PR whose comments still wait on the owner."""
    found = waiting(bodies, root)
    if found is None:
        return []
    index, phrase, line = found
    marker = config.get('push-guard.decision_marker', root)
    return [f'decision-wait: comment {index + 1} of PR #{number or "?"} waits on an owner decision ("{phrase}": '
            f'{line[:120]!r}) and no later comment records a "{marker}" line. DECIDE, THEN REPORT (Daniel 2026-10-26 '
            f'21:29): pick the safest reversible option (never weaken a check, add a secret, touch production or move '
            f'the source of truth), act on it, and record it in a PR comment line that starts with "{marker}"']
