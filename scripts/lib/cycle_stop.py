"""The cycle's turn guard (I-0d1c3a25): `scripts/cycle on|off|status` and the Claude Code Stop hook `scripts/hooks/cycle-stop`.

In a Claude Code session a reply with no tool call ends the turn, and the flow sits idle until a human writes. While the
cycle marker `.gate/cycle.on` exists, the Stop hook asks once, on the first attempt to end a turn, the Vigia's question
(the Torre, 09/11): is the standing determination done; if not and the next concrete step is known, take it without
ending the turn; if not known, end with a short status of where the work stopped, so the Torre carries it on. A
`STOP: <reason>` from the closed list (SEMENTE section 6) still ends the turn at once. With no marker (an interactive
session) every stop is allowed; the second attempt (`stop_hook_active`) is allowed too, so it cannot loop. The
marker's text, other than `on`, names the determination.
"""
import json
from pathlib import Path
import re
import sys

import config

ROOT = Path(__file__).resolve().parent.parent.parent
MARKER = ROOT / '.gate' / 'cycle.on'
REASONS = ('login', 'credential', 'money', 'people', 'quota')
STOP = re.compile(r'^\s*STOP:\s*(' + '|'.join(REASONS) + r')\b')
# The Vigia's rule (the Torre, 09/11): one concrete question, not a slogan that recycles the cycle. The marker's text, when
# it has one, names the standing determination; the next stop attempt (stop_hook_active) always ends the turn.
CONTINUE = ('Is the standing determination ({determination}) done? If not and you know the next concrete step, take that '
            'step now without ending the turn. If you do not know it, end the turn with a short status of where you '
            'stopped relative to the determination (no slogan), so the Torre can carry it on. (I-0d1c3a25)')


def default_determination():
    """The default standing determination from the configuration registry (flow.cycle_determination)."""
    return config.get('flow.cycle_determination')


def determination(marker=MARKER):
    """The standing determination the marker names (its text other than the bare 'on'), else the registered default."""
    try:
        text = marker.read_text().strip()
    except OSError:
        text = ''
    return text if text and text != 'on' else default_determination()


def last_assistant_text(transcript):
    """The text of the last assistant message in a Claude Code transcript (JSON lines), or '' when there is none."""
    text = ''
    try:
        lines = Path(transcript).read_text().splitlines()
    except (OSError, TypeError):
        return ''
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get('message') if isinstance(entry, dict) else None
        if not isinstance(message, dict) or message.get('role', entry.get('type')) != 'assistant':
            continue
        content = message.get('content')
        parts = [content] if isinstance(content, str) else [
            part.get('text', '') for part in content or [] if isinstance(part, dict) and part.get('type') == 'text']
        joined = '\n'.join(part for part in parts if part)
        if joined:
            text = joined
    return text


def decide(event, marker=MARKER):
    """None to let the turn end, or the Stop hook's block answer."""
    if not marker.exists() or event.get('stop_hook_active'):
        return None
    text = event.get('last_assistant_message') or last_assistant_text(event.get('transcript_path'))
    if STOP.match(text or ''):
        return None
    return {'decision': 'block', 'reason': CONTINUE.format(determination=determination(marker))}


def hook(stdin=sys.stdin, stdout=sys.stdout, marker=MARKER):
    try:
        event = json.loads(stdin.read() or '{}')
    except ValueError:
        event = {}
    answer = decide(event if isinstance(event, dict) else {}, marker)
    if answer:
        stdout.write(json.dumps(answer) + '\n')
    return 0


def main(argv=None, marker=MARKER):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else 'status'
    if command == 'hook':
        return hook(marker=marker)
    if command == 'on':
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('on\n')
    elif command == 'off':
        marker.unlink(missing_ok=True)
    elif command != 'status':
        print('usage: scripts/cycle on|off|status', file=sys.stderr)
        return 2
    print('cycle: ' + ('on' if marker.exists() else 'off'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
