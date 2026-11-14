"""The toolchain's download and install on a cold runner (RUNNER-SETUP-RESILIENCE, 09/11: 16 gate jobs ended
not_started with `download failed for python`). The downloader, the clock and the sleeps are injected: no network, no
waiting."""
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'cloud'))
import toolchain  # noqa: E402

URL = 'https://downloads.example.org/python.tar.gz?token=secret-of-the-test'


class Downloads(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dest = Path(tmp.name) / 'python'
        self.pauses, self.asked = [], []

    def flaky(self, failures):
        def download(url, dest):
            self.asked.append(url)
            if len(self.asked) <= failures:
                dest.write_bytes(b'half')
                raise urllib.error.URLError('temporary failure in name resolution')
            dest.write_bytes(b'whole')
        return download

    def run_it(self, failures):
        return toolchain._download_retrying(URL, self.dest, 'python', download=self.flaky(failures),
                                            sleep=self.pauses.append)

    def test_a_download_that_fails_twice_succeeds_on_the_third_try_after_one_and_two_seconds(self):
        self.run_it(2)
        self.assertEqual((self.dest.read_bytes(), self.pauses, len(self.asked)), (b'whole', [1, 2], 3))

    def test_a_download_that_never_works_fails_after_four_tries_with_pauses_of_one_two_and_four(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_it(99)
        message = str(caught.exception)
        self.assertEqual((self.pauses, len(self.asked), self.dest.exists()), ([1, 2, 4], 4, False))
        self.assertIn('download failed for python', message)  # what the runner reads to retry the run
        self.assertIn('downloads.example.org', message)
        self.assertIn('URLError', message)
        self.assertNotIn('secret-of-the-test', message)
        self.assertNotIn('/python.tar.gz', message)

    def test_the_first_try_that_works_sleeps_never(self):
        self.run_it(0)
        self.assertEqual((self.pauses, len(self.asked)), ([], 1))


class TheInstallLock(unittest.TestCase):
    def test_two_installers_of_one_root_never_hold_it_together_and_the_second_finds_the_first_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            holding, release, order = threading.Event(), threading.Event(), []

            def first():
                with toolchain._locked(root):
                    order.append('first in')
                    holding.set()
                    release.wait(5)
                    order.append('first done')

            def second():
                holding.wait(5)
                with toolchain._locked(root):
                    order.append('second in')

            threads = [threading.Thread(target=first), threading.Thread(target=second)]
            for thread in threads:
                thread.start()
            holding.wait(5)
            threads[1].join(0.3)
            self.assertTrue(threads[1].is_alive())  # waiting on the lock, not installing beside the first
            self.assertEqual(order, ['first in'])
            release.set()
            for thread in threads:
                thread.join(5)
            self.assertEqual(order, ['first in', 'first done', 'second in'])

    def test_a_waiter_that_finds_the_toolchain_installed_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / '.toolchain'
            root.mkdir()
            installs = []
            original = (toolchain.ROOT, toolchain.ready, toolchain._install, toolchain._share)
            state = {'ready': False}
            toolchain.ROOT = Path(tmp)
            toolchain.ready = lambda _root: state['ready']

            def install(_root):
                installs.append(1)
                state['ready'] = True
                return 0
            toolchain._install, toolchain._share = install, lambda _root: None
            self.addCleanup(lambda: (setattr(toolchain, 'ROOT', original[0]), setattr(toolchain, 'ready', original[1]),
                                     setattr(toolchain, '_install', original[2]),
                                     setattr(toolchain, '_share', original[3])))
            threads = [threading.Thread(target=toolchain.install) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            self.assertEqual(len(installs), 1)


if __name__ == '__main__':
    unittest.main()
