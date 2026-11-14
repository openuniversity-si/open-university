"""GV1: the gate status comment renders readably, is edited in place (never duplicated), is rate-bounded and never fails the gate. Hermetic."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
os.environ.setdefault("OU_CONFIG_STORE", "file")

import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402
from forge_origin_client import OriginClientError  # noqa: E402
import gate_status as status  # noqa: E402

SHA = "a" * 40
MODE = "dev"
MARK = config.get("gate.status_marker")


class FakeOrigin:
    """The Origin client (D-293: the one forge) as an in-memory change: comments read (GET), appended (POST) and edited
    (PATCH), and the check runs a commit status posts. Also the git refs the adapter checks its remote on."""

    HOST = "origin.test"

    def __init__(self, fail_patch=False):
        self.comments, self.calls, self.fail_patch = [], [], fail_patch
        self.statuses, self.status_error, self.offline = [], None, False
        self.waits = []  # max_wait_s of each write (GX-FIX-forge-rate: live edits never wait)

    def _call(self, method, target):
        if self.offline:
            raise OriginClientError("offline")
        self.calls.append((method, target))

    def url(self):
        return f"https://{self.HOST}/{config.get('forge-events.repo')}.git"

    def identity(self):
        return "tower-bot"

    def comments_of(self, repo, number, timeout=None):
        self._call("GET", f"{repo}/changes/{number}/comments")
        return list(self.comments)

    def append_comment(self, repo, number, body, timeout=None):
        self._call("POST", f"{repo}/changes/{number}/comments")
        self.comments.append({"id": len(self.comments) + 1, "body": body})
        return self.comments[-1]

    def edit_comment(self, repo, comment_id, body, timeout=None):
        self._call("PATCH", f"{repo}/comments/{comment_id}")
        if self.fail_patch:
            message = self.fail_patch if isinstance(self.fail_patch, str) else "404: the comment is gone"
            code = message.split(":", 1)[0]
            raise OriginClientError(message, status=int(code) if code.isdigit() else None)
        next(item for item in self.comments if item["id"] == comment_id)["body"] = body

    def publish_check_run(self, repo, sha, context, state, description, url=None):
        if self.status_error:
            raise OriginClientError(self.status_error, status=int(self.status_error.split(":", 1)[0]))
        self.statuses.append(dict(repo=repo, sha=sha, context=context, state=state, description=description))

    def writes(self):
        return [call for call in self.calls if call[0] in ("POST", "PATCH")]


def origin_adapter(forge, log):
    """The Origin adapter over `forge`, its writes' max_wait_s recorded in forge.waits."""
    adapter = forge_origin.OriginAdapter(_Client(forge), config.get("forge-events.repo"), log=log, refs=forge)
    upsert = adapter.upsert_comment

    def recorded(*args, **options):
        before = len(forge.writes())
        try:
            return upsert(*args, **options)
        finally:
            forge.waits.extend((call[0], options.get("max_wait_s")) for call in forge.writes()[before:])
    adapter.upsert_comment = recorded
    return adapter


class _Client:
    """The client surface OriginAdapter calls, answered by the FakeOrigin (whose `comments` is its stored list)."""

    def __init__(self, forge):
        self.forge = forge

    def comments(self, repo, number, timeout=None):
        return self.forge.comments_of(repo, number, timeout=timeout)

    def __getattr__(self, name):
        return getattr(self.forge, name)


def stage(logs, name, result="PASS", seconds=2.0, **extra):
    (pathlib.Path(logs) / f"{status.slug(name)}.stage.json").write_text(json.dumps(
        dict(name=name, result=result, exit=int(result != "PASS"), seconds=seconds, **extra)))


T0 = 1000.0
FAR = 10 ** 9


class Base(unittest.TestCase):
    def setUp(self):
        # Consumer unit tests inject local doubles; compatibility is exercised by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.enterContext(mock.patch.object(forge_events, 'checked_adapter', side_effect=lambda adapter, *args: adapter))
        read_config = config.get
        pinned = {'gate.status_enabled': True, 'forge-events.adapter': 'origin',  # FakeOrigin is the Origin client
                  'origin-client.git_hosts': [FakeOrigin.HOST]}
        self.enterContext(mock.patch.object(config, 'get', side_effect=lambda key, *args, **kwargs:
                          pinned[key] if key in pinned else read_config(key, *args, **kwargs)))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = pathlib.Path(self.tmp.name) / "reports" / SHA / "dev-1"
        self.logs.mkdir(parents=True)
        self.record = pathlib.Path(self.tmp.name)
        self.rest = FakeOrigin()
        self.ledger = forge_events.MemoryAdapter()  # GX-25: lifecycle events and the step ledger stay in memory
        self.adapter = origin_adapter(self.rest, self.ledger)
        self.enterContext(mock.patch.dict(forge_events.ADAPTERS, {'origin': lambda: self.adapter}))
        # The event log (forge-events.log_adapter) is this in-memory ledger too, so the verdict hooks a test drives read
        # and write it and never the live control plane: with its token in the environment, slo.collect read every PR
        # channel of the real log (46 reads, ~35 s per verdict) and judged the hooks on production data, not the fixture.
        log = read_config('forge-events.log_adapter')
        if log != pinned['forge-events.adapter']:
            self.enterContext(mock.patch.dict(forge_events.ADAPTERS, {log: lambda: self.ledger}))
        self.pub = status.Publisher()
        self.pub.events = forge_events.ForgeEvents(self.ledger, forge_events.SystemClock(), "gate_report", "gate:status")
        (self.logs / "plan.json").write_text(json.dumps({"kind": "scoped", "stages": ["structure check", "script tests"]}))

    def begin(self, now=T0):
        status.begin(self.logs, SHA, 573, MODE, self.record, publisher=self.pub, now=now)


class CallSites(Base):
    def test_disabled_panel_does_no_forge_or_eta_work(self):
        read_config = config.get
        with mock.patch.object(config, 'get', side_effect=lambda key, *args, **kwargs:
                               False if key in ('gate.status_enabled', 'gate.check_run_enabled') else read_config(key, *args, **kwargs)), \
                mock.patch.object(status, 'Publisher') as publisher, mock.patch.object(status, 'expectation') as eta:
            status.begin(self.logs, SHA, 573, MODE, self.record)
        publisher.assert_not_called()
        eta.assert_not_called()
        self.assertFalse((self.logs / status.STATE_FILE).exists())

    def test_final_from_report_reads_the_logs(self):
        self.begin()
        stage(self.logs, "script tests", result="FAIL")
        (self.logs / "script-tests.json").write_text(json.dumps(
            [{"test": "scripts/tests/a.test.sh", "result": "FAIL", "tail": ["AssertionError: nope"]}]))
        report = dict(sha=SHA, result="FAIL", stages=status_stages(self.logs))
        status.final_from_report(self.logs, report, [{"type": "gate.failed"}], publisher=self.pub, now=2000.0)
        body = self.rest.comments[0]["body"]
        self.assertIn("**BLOCKS**", body)
        self.assertIn("scripts/tests/a.test.sh", body)
        self.assertIn('"type":"gate.failed"', body)

    def test_without_a_publisher_the_verdict_hooks_run_detached_after_the_verdict(self):
        """GATE-SPEED R4 (D-092): the run answers first; the hooks start in their own session with the verdict."""
        self.begin()
        verdict = {"type": "gate.passed", "event_id": "e", "payload": {"tier": 1}}
        with mock.patch.object(status, "Publisher", return_value=self.pub), \
                mock.patch("subprocess.Popen") as started, mock.patch.object(status, "verdict_hooks") as inline:
            status.final(self.logs, dict(sha=SHA, result="PASS", stages=[]), [], 0, [], [], [verdict], now=T0)
        inline.assert_not_called()
        argv, options = started.call_args.args[0], started.call_args.kwargs
        self.assertEqual(argv[argv.index("verdict-hooks"):], ["verdict-hooks", "--logs", str(self.logs)])
        self.assertTrue(options["start_new_session"])
        self.assertEqual(json.loads((self.logs / status.HOOKS_FILE).read_text()), verdict)
        with mock.patch.object(status, "Publisher", return_value=self.pub), mock.patch.object(status, "verdict_hooks") as run:
            self.assertEqual(status.main(["verdict-hooks", "--logs", str(self.logs)]), 0)
        self.assertEqual(run.call_args.args[1], verdict)

    def test_a_passed_publisher_or_inline_hooks_run_them_before_returning(self):
        self.begin()
        verdict = {"type": "gate.passed", "event_id": "e", "payload": {"tier": 1}}
        with mock.patch("subprocess.Popen") as started, mock.patch.object(status, "verdict_hooks") as inline:
            status.final(self.logs, dict(sha=SHA, result="PASS", stages=[]), [], 0, [], [], [verdict], publisher=self.pub,
                         now=T0)
        started.assert_not_called()
        self.assertEqual(inline.call_args.args[1], verdict)

    def test_final_without_state_is_a_no_op(self):
        (self.logs / status.STATE_FILE).unlink(missing_ok=True)
        self.assertFalse(status.final_from_report(self.logs, dict(sha=SHA, result="PASS", stages=[]), publisher=self.pub))
        self.assertEqual(self.rest.calls, [])

    def test_runner_step_is_silent_and_exact_without_a_status(self):
        import subprocess
        script = f'logs={self.logs}; source {ROOT}/scripts/lib/gate-runner.sh; step demo . true; step bad . false; echo rc=$?'
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=ROOT)
        self.assertIn("PASS demo", done.stdout)
        self.assertIn("FAIL bad", done.stdout)
        self.assertFalse((self.logs / "status.log").exists())
        self.assertFalse((self.logs / status.STATE_FILE).exists())


class Redaction(unittest.TestCase):
    """GX-16: the failing-test rows go through redact() before any forge sees the body (moved from github_cli, D-293)."""

    def test_redact_scrubs_tokens_and_urls(self):
        fill = 'fixture' * len(MODE)
        token = 'gh' + 'p_' + fill
        secret = 'opaque-fixture-credential'
        scheme = '://'.join  # a URL with credentials, spelled so no literal names one
        values = [token, 'Bearer credential-value', scheme(('postgresql', 'user:pass@db/private')),
                  scheme(('https', 'user:pass@forge.test/path?token=value')), 'token=arbitrary-value',
                  'github_' + 'pat_' + fill, 'crsr' + '_' + fill, secret]
        with mock.patch.dict(os.environ, {'CURSOR_API_KEY': secret}):
            clean = status.redact(' '.join(values))
        for value in values:
            self.assertNotIn(value, clean)


def status_stages(logs):
    return [json.loads(path.read_text()) for path in sorted(pathlib.Path(logs).glob("*.stage.json"))]


if __name__ == "__main__":
    unittest.main()
