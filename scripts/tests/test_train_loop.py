"""The train's restart loop (D-156). Hermetic: the serve and the sleep are plain callables, the checkout a throwaway repository."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import train_loop  # noqa: E402


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        subprocess.run(['git', 'init', '-q', self.tmp.name], check=True)

    def test_it_starts_the_train_again_after_every_exit_and_sleeps_between_starts_only(self):
        exits, sleeps, lines = [], [], []
        count = len('abc')

        def serve():
            exits.append(len(exits))
            return len(exits)

        started = train_loop.loop(self.tmp.name, len('xy'), iterations=count, serve=serve, sleep=sleeps.append, out=lines.append)
        self.assertEqual((started, len(exits)), (count, count))
        self.assertEqual(len(sleeps), count - 1)
        self.assertTrue(any('exited' in line for line in lines))

    def test_the_watch_runs_once_per_new_tip_and_not_again_for_the_same_one(self):
        subprocess.run(['git', '-C', self.tmp.name, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'one'], check=True)
        seen = []
        train_loop.loop(self.tmp.name, 0, iterations=len('abc'), serve=lambda: 0, sleep=lambda seconds: None, out=lambda line: None,
                        watch=seen.append)
        self.assertEqual(len(seen), 1)

    def test_the_watcher_calls_watch_when_the_tip_moves_while_serve_runs(self):
        import threading
        subprocess.run(['git', '-C', self.tmp.name, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'one'], check=True)
        stop, seen = threading.Event(), []

        def watch(checkout):
            seen.append(checkout)
            stop.set()

        train_loop.watcher(self.tmp.name, watch, 0, stop, out=lambda line: None, refresh_checkout=lambda checkout: 0)
        self.assertEqual(seen, [self.tmp.name])

    def test_a_checkout_that_cannot_refresh_is_reported_and_still_served(self):
        lines = []
        started = train_loop.loop(self.tmp.name, 0, iterations=1, serve=lambda: 0, sleep=lambda seconds: None, out=lines.append)
        self.assertEqual(started, 1)
        self.assertTrue(any('not refreshed' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
