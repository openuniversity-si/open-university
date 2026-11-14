"""GV1 gate status: live (TX24: one file per feature; fixtures in scripts/tests/test_gate_status.py)."""
import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from test_gate_status import Base, FAR, MARK, MODE, SHA, T0, stage  # noqa: E402,F401
import config  # noqa: E402
import gate_status as status  # noqa: E402


LIVE_WALL_S = json.loads((pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'gate-eta.json').read_text())['started']['live_wall_s']


class Live(Base):
    def test_start_lists_planned_stages_with_history_eta(self):
        old = pathlib.Path(self.tmp.name) / "reports" / "b" / "dev-0"
        old.mkdir(parents=True)
        (old / "stages.json").write_text("{}")
        stage(old, "structure check", seconds=10)
        stage(old, "schema compat", seconds=30)
        # Two stages with no edge between them, so the critical path is the longer one (OU-DECOUPLE F5, D-113).
        (self.logs / "plan.json").write_text(json.dumps({"kind": "scoped", "stages": ["structure check", "schema compat"]}))
        self.begin()
        body = self.rest.comments[0]["body"]
        self.assertTrue(body.startswith(f"{MARK}\n<!-- head sha={SHA} mode={MODE} -->\n"))
        self.assertIn("| structure check | ⏳ pending | – | 10s |", body)
        self.assertIn("expected time left", body)
        self.assertIn(f"{status.seconds_text(LIVE_WALL_S)} of {status.seconds_text(LIVE_WALL_S)} (critical path", body)  # the longest path, not the sum

    def test_a_fresh_container_never_says_no_history(self):
        self.begin()
        body = self.rest.comments[0]["body"]
        fallback = status.seconds_text(config.get("gate-eta.fallback_stage_s"))
        self.assertNotIn("no history", body)
        self.assertIn(f"| structure check | ⏳ pending | – | {fallback} |", body)

    def test_one_comment_edited_in_place_and_rate_bounded(self):
        interval = config.get("gate.status_min_interval_s")
        self.begin(T0)
        status.stage_event(self.logs, "structure check", False, publisher=self.pub, now=T0 + interval + 1)
        self.assertEqual(len(self.rest.writes()), 1)  # a stage start never edits the comment (GX-16)
        stage(self.logs, "structure check", seconds=3)
        status.stage_event(self.logs, "structure check", True, publisher=self.pub, now=T0 + interval / 2)
        self.assertEqual(len(self.rest.writes()), 1)  # a stage end inside the interval: state saved, nothing written
        status.stage_event(self.logs, "structure check", True, publisher=self.pub, now=T0 + interval + 1)
        self.assertEqual([call[0] for call in self.rest.writes()], ["POST", "PATCH"])
        self.assertEqual(len(self.rest.comments), 1)
        self.assertIn("| structure check | ✅ passed | 3s |", self.rest.comments[0]["body"])

    def test_a_later_process_finds_the_comment_by_marker(self):
        self.begin()
        (self.logs / status.STATE_FILE).unlink()
        status.Publisher().publish({"sha": SHA, "mode": MODE, "pr": 573, "comment_id": None}, MARK + "\nx")
        self.assertEqual(len(self.rest.comments), 1)

    def test_other_head_or_mode_is_the_same_comment_and_a_different_one_when_the_switch_is_off(self):
        self.begin()
        other = status.Publisher()
        other.publish({"sha": SHA.replace("a", "b"), "mode": MODE, "pr": 573, "comment_id": None}, MARK + "\ny")
        self.assertEqual(len(self.rest.comments), 1)
        real = config.get
        with mock.patch.object(config, "get", lambda key, *a: False if key == "gate.status_one_per_pr" else real(key, *a)):
            self.assertIn("sha=" + SHA.replace("a", "b"), status.marker_line(SHA.replace("a", "b"), MODE))
        # the pinned gate's advisory view is its own comment: it never overwrites the PR's status comment
        self.assertNotEqual(status.marker_line(SHA, MODE + "+advisory"), status.marker_line(SHA, MODE))

    def test_an_edit_of_a_deleted_comment_creates_a_new_one_and_errors_never_raise(self):
        self.begin()
        self.rest.fail_patch = True  # 404: the comment is gone
        status.stage_event(self.logs, "structure check", True, publisher=self.pub, now=FAR)
        self.assertEqual(len(self.rest.comments), 2)

        self.rest.offline = True  # every call to the forge fails
        status.stage_event(self.logs, "structure check", True, publisher=status.Publisher(), now=FAR * FAR)

    def test_a_refused_edit_is_never_reposted(self):
        """GX-FIX-forge-rate: a rate-limited (or any non-404) edit keeps the one comment; the next edit carries it."""
        self.begin()
        self.rest.fail_patch = "429: rate-limited by the forge"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status.stage_event(self.logs, "structure check", True, publisher=self.pub)
        self.assertEqual(len(self.rest.comments), 1)
        self.assertIn("gate status: not published", err.getvalue())

    def test_reruns_on_the_same_head_and_mode_edit_in_place_and_a_new_head_makes_one(self):
        self.begin()
        pr = json.loads((self.logs / status.STATE_FILE).read_text())["pr"]
        for _rerun in ("second", "third", "fourth"):  # later runs of the same (sha, mode) start without the stored id
            (self.logs / status.STATE_FILE).unlink()
            self.begin()
        self.assertEqual([call[0] for call in self.rest.writes()], ["POST", "PATCH", "PATCH", "PATCH"])
        head = SHA.replace("a", "b")
        other = self.logs.parent.parent / head / self.logs.name
        other.mkdir(parents=True)
        (other / "plan.json").write_text((self.logs / "plan.json").read_text())
        status.begin(other, head, pr, MODE, self.record, publisher=self.pub)
        self.assertEqual(len(self.rest.comments), 1)  # GX-16: one comment per PR across heads
        body = self.rest.comments[0]["body"]
        self.assertIn(f"<!-- head sha={head} mode={MODE} -->", body)
        self.assertIn(f"- head `{status.short(SHA)}` {MODE}: superseded before a verdict", body)

    def test_live_edits_never_wait_for_the_write_budget_and_forced_ones_may(self):
        self.begin()
        status.stage_event(self.logs, "structure check", True, publisher=self.pub, now=FAR)
        self.assertEqual(self.rest.waits, [("POST", None), ("PATCH", 0)])

    def test_the_second_begin_only_replans_and_writes_nothing(self):
        """GX-16 (F-10): gate-local calls begin again when the scoped plan arrives; one POST, one pending status."""
        self.begin()
        (self.logs / "plan.json").write_text(json.dumps({"kind": "scoped", "stages": ["structure check"]}))
        self.begin(now=T0 + 1)
        self.assertEqual([call[0] for call in self.rest.writes()], ["POST"])
        self.assertEqual(len(self.rest.statuses), 1)
        self.assertEqual(json.loads((self.logs / status.STATE_FILE).read_text())["planned"], ["structure check"])

    def test_a_signature_is_redacted_and_a_red_row_names_its_class_and_log(self):
        self.begin()
        (self.logs / "structure_check.log").write_text(f"boom\n{config.get('gate.class_line_prefix')} structure check\tcode\n")
        report = dict(sha=SHA, result="FAIL", stages=[{"name": "structure check", "result": "FAIL", "seconds": 2}])
        failing = [{"id": "t1", "stage": "structure check", "signature": "token=ghp_abcdefghijklmnop leaked"}]
        status.final(self.logs, report, failing, 1, [], [], [], publisher=self.pub, now=FAR)
        body = self.rest.comments[0]["body"]
        self.assertNotIn("ghp_abcdefghijklmnop", body)
        self.assertIn("failed (class code) · log `", body)
        self.assertIn("structure_check.log`", body)


    def test_no_state_no_calls(self):
        status.stage_event(self.logs, "structure check", False, publisher=self.pub)
        self.assertEqual(self.rest.calls, [])


if __name__ == "__main__":
    unittest.main()
