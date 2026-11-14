"""BOARD (CANALE2): the flow's state on a fixed set of comments of one issue, edited in place, never added to.

A section is one comment whose first line is its marker (`<!-- tower-board:<key> -->`). refresh(texts) reads the board issue's
comments once and, for each section given:
  - edits the comment that carries its marker when its text changed (rewritten, never accumulated);
  - creates it when none carries the marker, or when the edit answers 404 (a comment deleted by hand is recreated once);
  - converges: when several comments carry one marker (two writers that both found none and both created), the lowest id is
    kept and the others are deleted, so any number of writers on any machine end with one comment per section;
  - cuts a text above the size limit at a line end, closes it with a pointer line, and appends the full text to the diary
    ref (refs/heads/<forge-events.board_overflow_ref>, create and fast-forward over git, D-070), never to another comment.

render(sections, events) builds each section's text from the newest events of its kinds (the git-ref log of E1, D-273).
The comments port is forge_github.IssueComments (one issue, REST in the GitHub adapter, D-069 item 7); the tests give an
in-memory one.
"""
MARKER = '<!-- tower-board:{key} -->'


class Gone(RuntimeError):
    """The comment to edit no longer exists (404)."""


def marker(key):
    return MARKER.format(key=key)


class Board:
    def __init__(self, comments, max_chars, diary=None, diary_ref=None, attempts=None):
        self.comments, self.max_chars = comments, max_chars
        self.diary, self.diary_ref, self.attempts = diary, diary_ref, attempts
        self.overflowed = []  # (key, length) of each section cut in this process, for the caller and the tests

    def fit(self, key, text):
        """(body, full): the comment body (marker first, within max_chars) and the full text when it was cut, else None."""
        body = f'{marker(key)}\n{text.rstrip()}\n'
        if len(body) <= self.max_chars:
            return body, None
        pointer = (f'\n_(cut: {len(body)} characters, above the comment limit; the full section is the newest '
                   f'`{key}` record of `refs/heads/{self.diary_ref}`)_\n')
        room = self.max_chars - len(pointer)
        cut = body.rfind('\n', 0, room)
        return body[:cut if cut > 0 else room] + pointer, body

    def _keep(self, key, ids):
        """The lowest id of a section's comments; the others are deleted (two writers converge to one comment)."""
        keep, *extra = sorted(ids)
        for comment_id in extra:
            self.comments.delete(comment_id)
        return keep

    def refresh(self, texts):
        """Write each section of `texts` ({key: text}); returns {key: comment id}."""
        found = {}
        current = {}
        for comment_id, body in self.comments.list():
            first = body.split('\n', 1)[0]
            found.setdefault(first, []).append(comment_id)
            current[comment_id] = body
        written = {}
        for key, text in texts.items():
            body, full = self.fit(key, text)
            ids = found.get(marker(key), [])
            comment_id = self._keep(key, ids) if ids else None
            if comment_id is not None and current.get(comment_id) == body:
                written[key] = comment_id
                continue
            if full is not None and self.diary is not None:
                self.diary.append(self.diary_ref, {'board': key, 'text': full}, self.attempts)
                self.overflowed.append((key, len(full)))
            if comment_id is not None:
                try:
                    self.comments.edit(comment_id, body)
                    written[key] = comment_id
                    continue
                except Gone:
                    pass
            created = self.comments.create(body)
            # converge: a rival may have created the same section at the same moment; the lowest id stays
            again = [cid for cid, other in self.comments.list() if other.split('\n', 1)[0] == marker(key)]
            written[key] = self._keep(key, again) if again else created
        return written


def render(sections, events, titles=None):
    """{key: text} of each section ({key: [kinds]}) from events (oldest first): per kind, how many the window holds and the
    newest one's time, sha and PR. A section with none of its kinds says so."""
    titles = titles or {}
    out = {}
    for key, kinds in sections.items():
        lines = [f'### {titles.get(key, key)}', '', '| Kind | Events in the window | Newest | Subject |', '|---|---|---|---|']
        for kind in kinds:
            mine = [event for event in events if event.get('type') == kind]
            if not mine:
                lines.append(f'| `{kind}` | 0 | | |')
                continue
            newest = mine[-1]
            payload = newest.get('payload') or {}
            subject = ' '.join(part for part in (
                f"`{str(payload.get('sha'))[:8]}`" if payload.get('sha') else '',
                f"#{payload['pr']}" if payload.get('pr') else '') if part)
            lines.append(f"| `{kind}` | {len(mine)} | {newest.get('occurred_at') or newest.get('at') or ''} | {subject} |")
        out[key] = '\n'.join(lines)
    return out

