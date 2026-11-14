"""F80: the Claude Code PostToolUse hook `scripts/hooks/bash-trim` that trims a long Bash output before the model sees it.

A lane's long Bash outputs were its costliest reads (03/11: a median of 4 calls over 2k tokens, 154k weighted; one
whole-file `cat` cost 82k). Above `flow.bash_trim_bytes` (stdout plus stderr, about 2k tokens) the hook answers with
`hookSpecificOutput.updatedToolOutput`, which Claude Code documents as replacing a tool's output for built-in tools too:
the head and the tail of each stream, cut on line ends, and a one-line hint to read the middle by range with `rg -n` or
`sed -n 'a,bp'`. A short output, an image, a non-Bash call or an event it cannot read gets no answer, so the original
output stands. The command itself already ran; only what the model reads changes.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

HINT = ('[bash-trim F80: {total} bytes, over {limit}; showing the head and the tail, {cut} bytes omitted. '
        "Read the middle by range: `rg -n PATTERN FILE` or `sed -n 'a,bp' FILE`, or pipe to `| tail -n N`.]")


def limit():
    """The threshold in bytes: `flow.bash_trim_bytes` from the registry; None when it cannot be read, and then
    nothing is trimmed (a broken registry must not break every Bash call)."""
    try:
        import config
        return int(config.get('flow.bash_trim_bytes'))
    except Exception:  # noqa: BLE001
        return None


def _cut(text, budget):
    """(head, tail, omitted bytes) of `text` within `budget` bytes, cut on line ends when a line end is near."""
    data = text.encode('utf-8', 'replace')
    half = max(budget >> 1, 1)
    if len(data) <= budget:
        return text, '', 0
    head, tail = data[:half], data[-half:]
    newline = head.rfind(b'\n')
    if newline >= half >> 1:
        head = head[:newline + 1]
    newline = tail.find(b'\n')
    if 0 <= newline < half >> 1:
        tail = tail[newline + 1:]
    return (head.decode('utf-8', 'ignore'), tail.decode('utf-8', 'ignore'),
            len(data) - len(head) - len(tail))


def trim(response, max_bytes):
    """The trimmed Bash output object, or None when it stays as it is."""
    if not isinstance(response, dict) or response.get('isImage'):
        return None
    stdout, stderr = response.get('stdout') or '', response.get('stderr') or ''
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None
    sizes = (len(stdout.encode('utf-8', 'replace')), len(stderr.encode('utf-8', 'replace')))
    total = sum(sizes)
    if total <= max_bytes:
        return None
    out = dict(response)
    cut = 0
    for name, text, size in (('stdout', stdout, sizes[0]), ('stderr', stderr, sizes[1])):
        budget = max_bytes * size // total
        head, tail, omitted = _cut(text, budget)
        cut += omitted
        if omitted:
            gap = '' if head.endswith('\n') or not head else '\n'
            out[name] = f'{head}{gap}... [{omitted} bytes omitted] ...\n{tail}'
    hint = HINT.format(total=total, limit=max_bytes, cut=cut)
    gap = '' if out['stdout'].endswith('\n') else '\n'
    out['stdout'] = f"{out['stdout']}{gap}{hint}"
    return out


def decide(event, max_bytes=None):
    """None to keep the output, or the PostToolUse answer that replaces it."""
    if not isinstance(event, dict) or event.get('tool_name') != 'Bash':
        return None
    max_bytes = limit() if max_bytes is None else max_bytes
    trimmed = None if max_bytes is None else trim(event.get('tool_response'), max_bytes)
    if trimmed is None:
        return None
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'updatedToolOutput': trimmed}}


def hook(stdin=sys.stdin, stdout=sys.stdout, max_bytes=None):
    try:
        event = json.loads(stdin.read() or '{}')
    except ValueError:
        return 0
    answer = decide(event, max_bytes)
    if answer is not None:
        stdout.write(json.dumps(answer))
    return 0


if __name__ == '__main__':
    sys.exit(hook())
