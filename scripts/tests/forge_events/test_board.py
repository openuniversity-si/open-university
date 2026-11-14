"""BOARD (CANALE2): the board's four proofs. Rewritten, not accumulated; two writers converge to one comment per section; a
comment deleted by hand is recreated once; a section above the size limit is cut, its full text on the diary ref."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))

import config  # noqa: E402
import forge_board  # noqa: E402


class Comments:
    """One issue's comments in memory: ids rise, a deleted id never comes back (as on GitHub)."""

    def __init__(self):
        self.held, self.next_id, self.writes = {}, 1, []

    def list(self):
        return sorted(self.held.items())

    def create(self, body):
        comment_id, self.next_id = self.next_id, self.next_id + 1
        self.held[comment_id] = body
        self.writes.append(('create', comment_id))
        return comment_id

    def edit(self, comment_id, body):
        if comment_id not in self.held:
            raise forge_board.Gone(comment_id)
        self.held[comment_id] = body
        self.writes.append(('edit', comment_id))

    def delete(self, comment_id):
        self.held.pop(comment_id, None)
        self.writes.append(('delete', comment_id))


class Diary:
    def __init__(self):
        self.records = []

    def append(self, name, record, attempts):
        self.records.append((name, record))
        return 'sha'


class Racing(Comments):
    """Two writers that both read the issue before either created: the first list() of each refresh sees no section."""

    def __init__(self):
        super().__init__()
        self.blind = 0

    def list(self):
        if self.blind:
            self.blind -= 1
            return []
        return super().list()


def board(comments, diary=None):
    return forge_board.Board(comments, config.get('forge-events.board_comment_max_chars'), diary, 'train/board', 1)


def bodies(comments, key):
    return [body for _, body in comments.list() if body.split('\n', 1)[0] == forge_board.marker(key)]


class BoardProofs(unittest.TestCase):
    def test_a_section_is_rewritten_not_accumulated(self):
        comments = Comments()
        for text in ('first state', 'second state', 'third state'):
            board(comments).refresh({'train': text})
        self.assertEqual(bodies(comments, 'train'), [f"{forge_board.marker('train')}\nthird state\n"])

    def test_an_unchanged_section_is_not_written(self):
        comments = Comments()
        board(comments).refresh({'train': 'same'})
        writes = list(comments.writes)
        board(comments).refresh({'train': 'same'})
        self.assertEqual(comments.writes, writes)

    def test_two_writers_that_both_created_converge_to_the_lowest_id(self):
        comments = Racing()
        first = board(comments)
        second = board(comments)
        # both read an empty board, then both write: the convergence after each create keeps one comment
        comments.blind = 1
        kept_a = first.refresh({'train': 'from a'})['train']
        comments.blind = 1
        kept_b = second.refresh({'train': 'from b'})['train']
        self.assertEqual(len(bodies(comments, 'train')), 1)
        self.assertEqual(kept_a, kept_b)
        self.assertEqual(kept_a, min(comment_id for comment_id, _ in comments.list()))

    def test_a_comment_deleted_by_hand_is_recreated_once(self):
        comments = Comments()
        sections = {'train': 'state', 'base': 'tip'}
        board(comments).refresh(sections)
        gone = next(cid for cid, body in comments.list() if body.startswith(forge_board.marker('train')))
        comments.delete(gone)
        board(comments).refresh(dict(sections, train='new state'))
        board(comments).refresh(dict(sections, train='newer state'))
        self.assertEqual(len(bodies(comments, 'train')), 1)
        self.assertEqual(len(comments.list()), len(sections))

    def test_a_stale_id_between_read_and_edit_is_recreated_not_lost(self):
        comments = Comments()
        board(comments).refresh({'train': 'state'})
        held = comments.list()

        class Stale(Comments):
            """The first read still shows the comment; it was deleted by hand before the edit."""
            read = False

            def list(self):
                if not self.read:
                    self.read = True
                    return held
                return super().list()

        stale = Stale()
        stale.next_id = comments.next_id
        board(stale).refresh({'train': 'new'})
        self.assertEqual(bodies(stale, 'train'), [f"{forge_board.marker('train')}\nnew\n"])

    def test_an_oversized_section_is_cut_and_its_full_text_goes_to_the_diary(self):
        comments, diary = Comments(), Diary()
        limit = config.get('forge-events.board_comment_max_chars')
        line = 'x' * (limit // len('0123456789'))
        text = '\n'.join([line] * len('0123456789abcdef'))
        board(comments, diary).refresh({'train': text})
        (body,) = bodies(comments, 'train')
        self.assertLessEqual(len(body), limit)
        self.assertIn('refs/heads/train/board', body)
        self.assertEqual(len(comments.list()), 1, 'no continuation comment')
        self.assertEqual(diary.records, [('train/board', {'board': 'train', 'text': f"{forge_board.marker('train')}\n{text}\n"})])


class Render(unittest.TestCase):
    def test_each_kind_shows_its_count_and_newest_event(self):
        events = [{'type': 'train.batch.started', 'occurred_at': 't1', 'payload': {'sha': 'a' * 40, 'pr': None}},
                  {'type': 'train.batch.started', 'occurred_at': 't2', 'payload': {'sha': 'b' * 40, 'pr': None}}]
        text = forge_board.render({'train': ['train.batch.started', 'train.queue.empty']}, events)['train']
        self.assertIn('| `train.batch.started` | 2 | t2 | `bbbbbbbb` |', text)
        self.assertIn('| `train.queue.empty` | 0 | | |', text)


class Channel:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr


class Log:
    remote = True

    def __init__(self):
        self.held = []

    def append(self, channel, envelopes):
        self.held.extend((channel.pr, envelope) for envelope in envelopes)

    def read(self, channel):
        return [envelope for pr, envelope in self.held if pr == channel.pr]


class Refreshes:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def refresh(self, texts):
        if self.fail:
            raise RuntimeError('gh: exit 502 (http)')
        self.calls.append(sorted(texts))


SECTIONS = {'train': ['train.batch.started'], 'base': ['integration.advanced']}


def adapter(board):
    import forge_events
    return forge_events.BoardAdapter(Log(), board, SECTIONS, forge_board.render)


class BoardRouting(unittest.TestCase):
    """CANALE2: a board kind is appended to the log and refreshes only its own section; nothing else is written."""

    def test_a_board_kind_goes_to_the_log_and_refreshes_its_section(self):
        board = Refreshes()
        routed = adapter(board)
        routed.append(Channel('o/r', None), [{'type': 'train.batch.started', 'payload': {}}])
        self.assertEqual(board.calls, [['train']])
        self.assertEqual([e['type'] for e in routed.read(Channel('o/r', None))], ['train.batch.started'])

    def test_a_pr_channel_event_stays_on_the_log(self):
        board = Refreshes()
        routed = adapter(board)
        routed.append(Channel('o/r', 'a'), [{'type': 'train.batch.started', 'payload': {}}])
        self.assertEqual(board.calls, [])

    def test_a_failed_board_write_never_fails_the_append(self):
        routed = adapter(Refreshes(fail=True))
        routed.append(Channel('o/r', None), [{'type': 'integration.advanced', 'payload': {}}])
        self.assertEqual(len(routed.failures), 1)
        self.assertEqual(len(routed.read(Channel('o/r', None))), 1)

    def test_no_board_issue_keeps_the_board_kinds_where_the_adapter_puts_them(self):
        self.assertEqual(config.get('forge-events.board_issue'), 0, 'the board is off until its issue exists')


if __name__ == '__main__':
    unittest.main()
