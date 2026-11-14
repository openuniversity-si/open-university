"""The infrastructure's schemas, work and log (engine-infra-db; INFRA-DB 1, D-306, D-308).

The first migration under infra/db is applied to a throwaway database of the toolchain's PostgreSQL 18.6 (TI1,
scripts/lib/test_db.py), and the phase-1 acceptance test of ARQUITETURA-ALVO §10 runs on it: two managements, one with
goals in tables of its own and one of autonomous workers with none; the same job by a script without an AI session and by
an AI session; a person as an executor, in the schema only; one queue function ordering by priority, by arrival and by
deadline as each queue's policy says; and the refusals. Nothing in the tables changes between the cases (D-308: every
mechanism keeps its parameters, and its default is a value). The migration is the annex DDL and the acceptance test the
annex test, statement for statement. Local PostgreSQL only, no network.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import test_db  # noqa: E402

MIGRATION = ROOT / 'infra/db/migrations/0001_work_log.sql'
ACCEPTANCE = ROOT / 'scripts/tests/infra_db/acceptance.sql'
ANNEX = ROOT / 'docs/arquitetura-referencia/anexos'
RECORD = ROOT / 'docs/domain/decisions/D-308.md'
COMMENT = re.compile(r'--[^\n]*')
FOOTER = re.compile(r'^\(\d+ rows?\)$')
REFUSED = re.compile(r'NOTICE:\s+refused as expected: (.*)')


def statements(path):
    """What a SQL file sends to the server: its lines without comments and blank lines, so headers may differ."""
    return [line.rstrip() for line in COMMENT.sub('', path.read_text(encoding='utf-8')).splitlines() if line.strip()]


def results(stdout):
    """psql's quiet unaligned output (-q -A -F '|', footer on) as {header: rows}, the first result of each header."""
    found, block = {}, []
    for line in stdout.splitlines():
        if FOOTER.match(line):
            if block:
                found.setdefault(block[0], [row.split('|') for row in block[1:]])
            block = []
        else:
            block.append(line)
    return found


class Source(unittest.TestCase):
    """The code is the annex the architecture was accepted on, so the documented and the applied schema are one."""

    def test_the_migration_is_the_annex_ddl(self):
        self.assertEqual(statements(MIGRATION), statements(ANNEX / 'infra-v1.sql'))

    def test_the_acceptance_test_is_the_annex_test(self):
        self.assertEqual(statements(ACCEPTANCE), statements(ANNEX / 'infra-v1-aceite.sql'))

    def test_the_record_cites_daniel_and_names_this_proof(self):
        record = RECORD.read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_db.py', record)
        for said in ('Daniel 04/11 12:40 BRT', 'outra coisa é você simplesmente tirar o parâmetro', 'refines D-306'):
            self.assertIn(said, record)


class Acceptance(unittest.TestCase):
    """One database of its own: the migration, the acceptance test, then each mechanism read from what it printed."""

    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get('TEST_DATABASE_URL', '')
        cls.name = test_db.create(cls.url)
        parts = urlsplit(cls.url)
        cls.database = urlunsplit((parts.scheme, parts.netloc, '/' + cls.name, '', ''))
        try:
            cls.psql('-f', str(MIGRATION))
            done = cls.psql('-f', str(ACCEPTANCE))
        except BaseException:
            test_db.destroy(cls.url, cls.name)
            raise
        cls.printed = results(done.stdout)
        cls.refused = REFUSED.findall(done.stderr)

    @classmethod
    def tearDownClass(cls):
        test_db.destroy(cls.url, cls.name)

    @classmethod
    def psql(cls, *args):
        done = subprocess.run([str(test_db.psql_binary()), cls.database, '-X', '-q', '-A', '-F', '|',
                               '-v', 'ON_ERROR_STOP=1', *args], capture_output=True, text=True,
                              timeout=config.get('test-db.psql_timeout_s'), check=False)
        if done.returncode:
            raise AssertionError(f'psql {" ".join(args)} failed ({done.returncode}): {done.stderr.strip()}')
        return done

    def query(self, sql):
        return results(self.psql('-c', sql).stdout).popitem()[1]

    def test_each_queue_orders_by_its_own_policy(self):
        # One function, work.next_job, by rank, by arrival and by deadline: the policy is a value of the queue.
        self.assertEqual(self.printed['queue|next'],
                         [['ranked', 'rank-5'], ['fifo', 'fifo-first'], ['deadline', 'deadline-sooner']])

    def test_the_selector_asks_and_the_capacity_decides(self):
        # claude-sub comes first in any_of but has no slot left in its window, so the route takes codex-sub.
        self.assertEqual(self.printed['idempotency_key|routed_to'],
                         [['by-ai', 'codex-sub'], ['by-script', 'script-runner']])

    def test_the_same_job_runs_by_a_script_without_a_session_and_by_an_ai_session(self):
        self.assertEqual(self.printed['idempotency_key|executor|adapter|state'],
                         [['by-ai', 'codex-sub', 'agent-session', 'succeeded'],
                          ['by-script', 'script-runner', 'container', 'succeeded']])

    def test_retry_waits_longer_each_time_defaults_to_one_attempt_and_spares_the_lost(self):
        # Three attempts with 10 s then 20 s; the default of one attempt; an error the job names as never retryable;
        # an executor that vanished is dispatched again without spending an attempt.
        self.assertEqual(self.printed['k|step|state|wait'],
                         [['lost-executor', '1', 'queued', ''], ['non-retryable', '1', 'failed', ''],
                          ['retry-3', '1', 'queued', '00:00:10'], ['retry-3', '2', 'queued', '00:00:20'],
                          ['retry-3', '3', 'failed', ''], ['retry-default', '1', 'failed', '']])

    def test_the_landing_waits_for_its_checks(self):
        self.assertEqual(self.printed['next_after_checks'], [['landing']])

    def test_a_money_limit_stops_the_job_by_the_token_price(self):
        # 12,000 tokens at the price the tenant set make US$ 0.036, over its US$ 0.03 stop limit.
        self.assertEqual(self.printed['idempotency_key|state|usd'], [['money-limit', 'stopped', '0.036000']])

    def test_an_identical_input_comes_from_the_cache_without_a_run(self):
        self.assertEqual(self.printed['idempotency_key|state|runs'], [['memoized', 'succeeded', '0']])

    def test_management_keeps_its_goals_in_its_own_tables_and_measures_from_the_raw_log(self):
        self.assertEqual(self.printed['chave|audit_measured'], [['F135', 't']])

    def test_a_person_fits_as_an_executor_without_a_migration(self):
        # Dormant (Daniel 04/11 13:18): the adapter is a name, the agenda a capacity row, the jobs those of a queue.
        self.assertEqual(self.query("select e.adapter, e.tenant_id is null, c.account, c.slots, count(j.id) "
                                    "from work.executor e join work.capacity c on c.executor = e.name "
                                    "join work.job j on j.executor = e.name where e.name = 'pessoa' group by 1, 2, 3, 4"),
                         [['person-queue', 't', 'daniel', '1', '2']])

    def test_the_infrastructure_refuses_what_it_must(self):
        expected = ['executor "livre-own-key" belongs to another tenant',  # the private executor of another tenant
                    'violates check constraint "job_check"',  # a job with neither an executor nor a selector
                    'violates unique constraint "job_exclusive"',  # two landings on one branch
                    'event type "torre.bet.accepted" is not something the infrastructure observes',  # management's event
                    'a refuse limit of tenant ',  # a job over a refuse limit
                    'violates unique constraint "job_tenant_id_idempotency_key_key"']  # one idempotency key twice
        self.assertEqual(len(self.refused), len(expected), self.refused)
        for want, said in zip(expected, self.refused):
            self.assertIn(want, said)

    def test_no_name_of_management_and_thirteen_tables_in_two_schemas(self):
        self.assertEqual(self.printed['forbidden_names'], [['0']])
        self.assertEqual(self.printed['schemas'], [['gestao_torre,log,work']])  # gestao_torre is the test's management
        self.assertEqual(self.printed['infra_tables'], [['13']])

    def test_every_default_is_a_value_and_not_a_missing_parameter(self):
        # D-308: a queue without a policy, or a failure without a retry policy, would be the infrastructure choosing.
        rows = self.query("select table_name || '.' || column_name, column_default from information_schema.columns "
                          "where table_schema = 'work' and table_name || '.' || column_name in ('queue.policy', "
                          "'queue.config', 'job.queue', 'job.selector', 'job.max_attempts', 'job.backoff_initial', "
                          "'job.backoff_factor', 'job.backoff_max', 'job.retry_on', 'job.non_retryable', 'job.memoize', "
                          "'dependency.condition') order by 1")
        self.assertEqual(dict(rows), {
            'dependency.condition': "'succeeded'::text", 'job.backoff_factor': '2',
            'job.backoff_initial': "'00:00:10'::interval", 'job.backoff_max': "'00:10:00'::interval",
            'job.max_attempts': '1', 'job.memoize': 'false', 'job.non_retryable': "'{}'::text[]",
            'job.queue': "'default'::text", 'job.retry_on': "'{failed,timed_out}'::text[]",
            'job.selector': "'{}'::jsonb", 'queue.config': "'{}'::jsonb", 'queue.policy': "'fifo'::text"})


if __name__ == '__main__':
    unittest.main()
