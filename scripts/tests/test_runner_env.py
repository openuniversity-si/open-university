#!/usr/bin/env python3
"""A check behaves the same on the box and on the infrastructure's runner (AWS3; shadow PRs #310 and #305).

The runner's checks get a bare environment (PATH, HOME=/tmp, USER, ...: infra/service/tower_infra/runner.py PASSED) and
the Tower runner hands a job TOWER_JOB_OWNER and TOWER_JOB_DEADLINE (service_budget); the box has neither, but has the
operator's tokens and credentials mode. A test that read either side was red on one judge and green on the other."""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import gate_graph  # noqa: E402
import gate_test_cache  # noqa: E402
import service_budget  # noqa: E402

# the heaviest and most environment-sensitive: the runner and its lock owner, the train, the delivery, the session
SAMPLE = ('service', 'train-role', 'deliver', 'claude-session')
PASSED = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'USER', 'LOGNAME', 'SHELL')  # tower_infra.runner.PASSED
JOB = {service_budget.OWNER_ENV: 'runner-1/job-7', service_budget.DEADLINE_ENV: '4102444800'}
# what the box's operator holds and a container does not
OPERATOR = ('GH_TOKEN', 'GITHUB_TOKEN', 'CURSOR_API_KEY', 'CURSOR_AUTH_TOKEN', 'OU_RUNNER_TOKEN', 'TOWER_EVENTS_TOKEN',
            'OU_CREDENTIALS', 'OU_RUNNER_KIND', 'OU_CONFIG_STORE')


# what the gate gives every script test (gate_test_cache) and what scripts/cloud/env.sh leaves in the check's process before
# it starts: as root it sets OU_ROOT_SESSION, and a shell without it runs scripts/cloud/root-session.sh again, which calls
# python3 through the shim when the container has no /usr/bin/python3 (the runner's: AWS7, the 3 claude-session failures)
GIT = ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_COUNT', 'OU_ROOT_SESSION')
WORKERS = 2  # eight heavy bash tests at once starve a 4-slot container's CPUs; the pairs of a script run together


def isolated(env, tmp, name):
    """`env` with its own HOME and TMPDIR under `tmp`: no nested run shares a cache, lock or state dir with another
    run of this test (the runner has 4 concurrent slots) or with the gate's own."""
    own = Path(tmp) / name
    own.mkdir(parents=True)
    return dict(env, TMPDIR=str(own), **({'HOME': str(own)} if env.get('HOME') == str(tmp) else {}))


def run(script, env):
    done = subprocess.run(['bash', str(ROOT / 'scripts' / 'tests' / f'{script}.test.sh')], capture_output=True, text=True,
                          env=env, cwd=ROOT, stdin=subprocess.DEVNULL)
    said = done.stdout + done.stderr
    # compact: the failing assertions first (the gate reports only the last 2000 characters of a check), then the tail
    evidence = '\n'.join(gate_graph.failure_lines(said)) if done.returncode else ''
    return done.returncode, (evidence + '\n' + said[-600:]).strip()[:1000]


class SameOnEveryJudge(unittest.TestCase):
    def environments(self, tmp):
        box = {key: value for key, value in os.environ.items() if key not in JOB}
        runner = {key: os.environ[key] for key in PASSED + GIT if key in os.environ}
        runner.update(HOME=tmp, TMPDIR=tmp, **JOB)
        for key in os.environ:  # the git settings of the gate (GIT_CONFIG_KEY_n / VALUE_n), which a container's check has too
            if key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
                runner[key] = os.environ[key]
        return box, runner

    def test_a_sample_of_the_script_tests_gives_the_same_result_with_the_runners_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            box, runner = self.environments(tmp)
            with ThreadPoolExecutor(WORKERS) as pool:
                started = {script: (pool.submit(run, script, isolated(box, tmp, f'{script}-box')),
                                    pool.submit(run, script, isolated(runner, tmp, f'{script}-runner'))) for script in SAMPLE}
            for script, (first, second) in started.items():
                with self.subTest(script=script):
                    on_box, on_runner = first.result(), second.result()
                    self.assertEqual(on_box[0], on_runner[0], f'runner rc={on_runner[0]}, box rc={on_box[0]}\nrunner: {on_runner[1]}\nbox: {on_box[1]}')
                    self.assertEqual(on_runner[0], 0, on_runner[1])

    def test_a_sample_does_not_depend_on_the_operators_tokens_or_the_job_variables_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            box, _ = self.environments(tmp)
            for name in OPERATOR:
                box.pop(name, None)
            for script in ('service', 'train-role'):
                with self.subTest(script=script):
                    code, said = run(script, isolated(dict(box, **JOB), tmp, f'{script}-tokens'))
                    self.assertEqual(code, 0, said)


class GateScrub(unittest.TestCase):
    def test_the_gate_keeps_the_tower_runners_job_variables_out_of_a_script_test(self):
        environ = {**JOB, 'PATH': '/bin', 'OU_GATE_TIER': 'x'}
        self.assertEqual(gate_test_cache.scrubbed(environ), sorted([*JOB, 'OU_GATE_TIER']))

    def test_every_variable_the_service_hands_a_job_is_scrubbed(self):
        names = {service_budget.OWNER_ENV, service_budget.DEADLINE_ENV}
        self.assertTrue(names <= set(gate_test_cache.scrubbed({name: '1' for name in names})))


if __name__ == '__main__':
    unittest.main()
