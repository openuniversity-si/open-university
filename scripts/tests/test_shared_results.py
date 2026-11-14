"""GATE-SPEED F10 (D-130): script test PASSes shared between boxes by their input key. Hermetic: a local bare remote."""
import contextlib
import errno
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import forge_git_ref  # noqa: E402
import gate_test_cache as cache  # noqa: E402
import shared_results  # noqa: E402

NOW = config.get("gate.test_cache_ttl_s") * (1 + 1)  # a moment late enough that "older than the ttl" exists
TTL = config.get("gate.test_cache_ttl_s")


def marker(key, at=NOW, source="box-a"):
    return {"key": key, "stored_at": at, "source": source, "test": "scripts/tests/a.test.sh"}


class Remote(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.remote, self.box = base / "remote.git", base / "box"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", str(self.box)], check=True)

    def store(self, box=None):
        refs = forge_git_ref.GitRefs(box or self.box, remote=str(self.remote))
        return shared_results.SharedResults(box or self.box, refs=refs)

    def test_a_box_reads_what_another_published(self):
        first = self.store()
        self.assertEqual(first.read(), {})  # no ref yet: nothing shared
        self.assertTrue(first.publish({}, {"k1": marker("k1")}, NOW))
        other = pathlib.Path(self._tmp.name) / "other"
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        self.assertEqual(self.store(other).read(), {"k1": marker("k1")})

    def test_a_record_past_the_argument_limit_still_publishes(self):
        # The record rides in the commit message; as a git argument it failed at 128 KB (E2BIG) and publish went quiet.
        store = self.store()
        big = {"big": dict(marker("big"), source="x" * os.sysconf("SC_ARG_MAX"))}
        self.assertTrue(store.publish({}, big, NOW))
        self.assertEqual(set(store.read()), {"big"})
        self.assertTrue(store.publish(store.read(), {"extra": marker("extra")}, NOW))
        self.assertEqual(set(store.read()), {"big", "extra"})

    def test_a_failed_publish_says_so_on_stderr(self):
        import io
        store = self.store()
        with mock.patch.object(store.refs, "append", side_effect=OSError(errno.E2BIG, "Argument list too long")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertFalse(store.publish({}, {"k1": marker("k1")}, NOW))
        self.assertIn("not published", err.getvalue())
        self.assertIn("OSError", err.getvalue())

    def test_a_publish_keeps_what_it_read_and_drops_what_expired(self):
        store = self.store()
        old, young = marker("old", at=NOW - TTL - 1), marker("young", at=NOW - 1)
        store.publish({}, {"young": young}, NOW)
        self.assertTrue(store.publish({"old": old, "young": young}, {"new": marker("new")}, NOW))
        self.assertEqual(sorted(store.read()), ["new", "young"])
        self.assertFalse(store.publish(store.read(), {}, NOW))  # nothing added: no push

    def test_an_unreadable_remote_is_no_result(self):
        refs = forge_git_ref.GitRefs(self.box, remote=str(pathlib.Path(self._tmp.name) / "absent.git"))
        store = shared_results.SharedResults(self.box, refs=refs)
        self.assertEqual(store.read(), {})
        self.assertFalse(store.publish({}, {"k": marker("k")}, NOW))


class Valid(unittest.TestCase):
    def test_only_a_pass_of_this_key_inside_the_ttl(self):
        self.assertEqual(shared_results.valid(marker("k"), "k", NOW, TTL), marker("k"))
        for wrong in (marker("other"), marker("k", at=NOW - TTL - 1), marker("k", at=NOW + 1), marker("k", at=True),
                      {"key": "k"}, None):
            self.assertIsNone(shared_results.valid(wrong, "k", NOW, TTL), wrong)

    def test_it_is_on_only_when_the_run_says_so(self):
        self.assertTrue(shared_results.enabled({shared_results.ENV: "1"}))
        self.assertFalse(shared_results.enabled({}))
        self.assertFalse(shared_results.enabled({shared_results.ENV: "0"}))


class GateDev(unittest.TestCase):
    """D-135: scripts/gate-dev runs its gate with the shared results on unless the caller turned them off."""

    def answer(self, env):
        with tempfile.TemporaryDirectory() as folder:
            tools = pathlib.Path(folder)
            (tools / "gate-dev").write_text((ROOT / "scripts" / "gate-dev").read_text())
            stub = tools / "gate-local"
            stub.write_text('#!/usr/bin/env bash\necho "shared=${OU_SHARED_RESULTS-unset}"\n')
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
            # D-291: gate-dev starts gate-local itself, so the stub gate here is all the run needs
            clean = {key: value for key, value in os.environ.items() if key != shared_results.ENV}
            done = subprocess.run(["bash", str(tools / "gate-dev"), "--pr", "1"], capture_output=True, text=True,
                                  env={**clean, **env})
        return done.stdout.strip()

    def test_it_is_on_by_default(self):
        self.assertEqual(self.answer({}), "shared=1")

    def test_a_caller_can_turn_it_off(self):
        self.assertEqual(self.answer({shared_results.ENV: "0"}), "shared=0")


class Run(unittest.TestCase):
    """gate_test_cache.run: a key another box judged PASS is not run here; the PASSes this run adds are published."""

    def run_two(self, held, local=False):
        published = []

        class Fake:
            def __init__(self, _root):
                pass

            def read(self):
                if local:
                    raise AssertionError('complete local proofs must not fetch the shared store')
                return dict(held)

            def publish(self, read, added, now):
                published.append((read, added))
                return True

        ran = []

        def commands(todo, workers, env, cwd, timings, ended=None):
            ran.extend(script for script, _ in todo)
            timings.update({script: 0 for script, _ in todo})
            return [{"name": script, "result": cache.gate_graph.PASS, "output": ""} for script, _ in todo]

        keys = {"scripts/tests/a.test.sh": "ka", "scripts/tests/b.test.sh": "kb"}
        with tempfile.TemporaryDirectory() as store, contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {shared_results.ENV: "1"}))
            stack.enter_context(mock.patch.object(cache.shared_results, "SharedResults", Fake))
            stack.enter_context(mock.patch.object(cache.gate_graph, "run_commands", side_effect=commands))
            stack.enter_context(mock.patch.object(cache, "key", side_effect=lambda script, *a, **k: keys[script]))
            stack.enter_context(mock.patch.object(cache, "_now", return_value=NOW))
            if local:
                stack.enter_context(mock.patch.object(cache, 'lookup', side_effect=lambda store, key, now:
                                                      marker(key, source='local-box')))
            results = cache.run(sorted(keys), ROOT, pathlib.Path(store), "run-1", ROOT, concurrency=1,
                                mapping={"tests": []})
        return ran, results, published

    def test_a_shared_pass_is_not_run_and_a_new_pass_is_published(self):
        ran, results, published = self.run_two({"ka": marker("ka", source="box-a")})
        self.assertEqual(ran, ["scripts/tests/b.test.sh"])
        self.assertEqual([(r["test"], r["cached"], r["source"]) for r in results],
                         [("scripts/tests/a.test.sh", True, "box-a"), ("scripts/tests/b.test.sh", False, "run-1")])
        [(read, added)] = published
        self.assertEqual((sorted(read), sorted(added)), (["ka"], ["kb"]))

    def test_a_script_test_never_sees_the_switch(self):
        self.assertIn(shared_results.ENV, cache.scrubbed({shared_results.ENV: "1", "PATH": "p"}))

    def test_complete_local_proofs_need_no_shared_read_or_write(self):
        ran, results, published = self.run_two({}, local=True)
        self.assertEqual(ran, [])
        self.assertTrue(all(row['cached'] and row['source'] == 'local-box' for row in results))
        self.assertEqual(published, [])


if __name__ == "__main__":
    unittest.main()
