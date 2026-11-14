"""SERVICE-ROLLOUT-OVERLAP (docs/operations/aws-revisao-arquitetura.md, finding 7): two dispatchers at once are safe.

The service's rollout stopped the only dispatcher before the new one started (MinimumHealthyPercent 0): the jobs made
meanwhile waited for it (p95 61 s, 102 s at most, measured 09 and 10/11). The new task starts beside the old one, as
the runner's does; for the minutes both are up, two service processes dispatch the same queues. What makes that safe is
in the statements (the claim's `for update skip locked`, the capacity's slot, the lease's fence): this test runs two
dispatch passes at the same time on real Postgres and each job is claimed once.

Needs TEST_DATABASE_URL (Postgres); each statement is its own session (the psql wrapper), so the two passes interleave.
"""
import os
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import mechanisms  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
JOBS = 8


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class TwoDispatchers(unittest.TestCase):
    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db
        self.world.port('PUT', '/v1/executors/script-runner/capacity/fargate', 'installation', {'slots': str(JOBS)})

    def test_two_dispatch_passes_at_once_claim_each_job_once(self):
        jobs = {self.world.job(f'job-{n}', 'true') for n in range(JOBS)}
        start, made, failed = threading.Barrier(2), [[], []], []

        def dispatcher(mine):
            try:
                start.wait(10)
                mine.extend(mechanisms.dispatch(self.db, '5 minutes'))
            except Exception as error:  # noqa: BLE001 - reported below: a pass that raises is the test's failure
                failed.append(error)
        threads = [threading.Thread(target=dispatcher, args=(mine,)) for mine in made]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(failed, [])
        claimed = [got['job'] for mine in made for got in mine]
        self.assertEqual((sorted(claimed), len(set(claimed))), (sorted(jobs), JOBS))  # every job, once, by one of the two
        runs = self.db.rows('select job_id::text, count(*) from work.run group by 1')
        self.assertEqual(sorted(runs), sorted((job, '1') for job in jobs))  # one run a job: no second hand-over
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [(str(JOBS),)])
        self.assertEqual(mechanisms.dispatch(self.db, '5 minutes'), [])  # and nothing is left for a third pass

    def test_two_reaps_at_once_give_an_expired_job_back_once(self):
        job = self.world.job('expired', 'true')
        mechanisms.dispatch(self.db, '5 minutes')
        self.db.rows("update work.job set lease_expires_at = clock_timestamp() - interval '1 second' where id = %(id)s::uuid",
                     {'id': job})
        start, reaped = threading.Barrier(2), []

        def reaper():
            start.wait(10)
            reaped.extend(mechanisms.reap(self.db))
        threads = [threading.Thread(target=reaper) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(reaped, [job])


if __name__ == '__main__':
    unittest.main()
