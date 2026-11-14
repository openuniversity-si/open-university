#!/usr/bin/env python3
"""The grace of a stage past its limit (gate-runner.sh, gate_run_limited): TERM first, and KILL only for a stage that is
still alive when the grace ends. A stage that dies on TERM must not cost the whole grace. Hermetic: temp dirs."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import config  # noqa: E402

LIMIT = GRACE = 1
LONG_GRACE = GRACE + GRACE + GRACE + GRACE + GRACE


def run_step(command, grace):
    """Run `step` of gate-runner.sh on a stage limited to LIMIT seconds with this grace; (rc, seconds, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        logs, lib = pathlib.Path(tmp) / "logs", pathlib.Path(tmp) / "lib"
        logs.mkdir()
        lib.mkdir()
        for name in ("gate_classify.py", "gate_status.py", "config.py", "json_schema.py"):
            (lib / name).symlink_to(ROOT / "scripts" / "lib" / name)
        fields = [LIMIT, grace, config.get("gate-gc.timeout_exit_code"), config.get("gate-gc.log_tail_lines")]
        (lib / "gate_gc.py").write_text("print(%r)\n" % "\t".join(str(field) for field in fields))
        script = f'logs="$1"; source "{ROOT}/scripts/lib/gate-runner.sh"; gate_lib_dir="$2"; step fixture "$3" bash -c "$4"'
        done = subprocess.run(["bash", "-c", script, "x", str(logs), str(lib), tmp, command],
                              capture_output=True, text=True, env={**os.environ, "OU_CONFIG_STORE": "file"})
        seconds = json.loads((logs / "fixture.stage.json").read_text())["seconds"]
        return done.returncode, seconds, done.stdout + done.stderr


class Grace(unittest.TestCase):
    def test_a_stage_that_dies_on_term_does_not_wait_out_the_grace(self):
        rc, seconds, _ = run_step("sleep infinity", LONG_GRACE)
        self.assertEqual(rc, config.get("gate-gc.timeout_exit_code"))
        self.assertLess(seconds, LIMIT + GRACE + GRACE)  # the limit plus slack, far under limit + LONG_GRACE

    def test_a_stage_that_ignores_term_is_killed_when_the_grace_ends(self):
        rc, seconds, out = run_step('trap "" TERM; sleep infinity', GRACE)
        self.assertEqual(rc, config.get("gate-gc.timeout_exit_code"))
        self.assertGreaterEqual(seconds, LIMIT + GRACE)  # it lived through the whole grace
        self.assertLess(seconds, LIMIT + GRACE + GRACE + GRACE)
        self.assertIn("FAIL fixture", out)


if __name__ == "__main__":
    unittest.main()
