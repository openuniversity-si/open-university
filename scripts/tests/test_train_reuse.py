"""Tier-2 reuse of exactly-matching attested proofs (GX-31): the switch, the key the train recomputes, the verified
lookup and the train's judge path. No network: a bare repository in a temporary directory and in-memory forges; the
trusted forge keeps only events posted by a writer trusted by the control-plane journal."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / 'lib'))
from test_train import REPO, ROOT, FakeForge, Fixture  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402
import gate_batch  # noqa: E402
import gate_digest  # noqa: E402
import gate_proof  # noqa: E402
import train  # noqa: E402
import train_reuse  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

TOOLCHAIN = hashlib.sha256(b'attested toolchain of this container').hexdigest()
SWITCH = 'train-reuse.reuse_attested_proofs'
CHECKOUT = ('config/registry', 'contracts/units', 'contracts/config', 'docs/domain', 'units')  # what the union plan reads


def setUpModule():
    """An empty change store chosen explicitly: registry values only (D-069 item 5)."""
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def one_byte(value):
    """`value` with its last character changed: a one-byte change of one input."""
    return value[:-1] + ('0' if value[-1] != '0' else '1')


class TrustedForge(FakeForge):
    """The remote journal refuses events from writers outside its declared trust set."""

    remote = True

    def __init__(self, origin):
        super().__init__(origin)
        self.trusted = {config.get('forge-events.control_token_env')}
        self.author = sorted(self.trusted)[0]
        self.authors = {}

    def append(self, channel, envelopes):
        for envelope in envelopes:
            self.authors[envelope['event_id']] = self.author
        super().append(channel, envelopes)

    def read(self, channel):
        return [event for event in super().read(channel) if self.authors.get(event.get('event_id')) in self.trusted]


class Reuse(Fixture):
    """The train over a trusted forge; the attestation is injected (TOOLCHAIN), gate_version is this checkout's."""

    forge_class = TrustedForge

    def base_files(self):
        """This checkout's registry and unit manifests, so gate_batch.plan derives the selection as on the train. Of the
        registry only the aggregates config reads (fixture_copy, GATE-SPEED F2): the per-key sources are 900 files."""
        return {str(path.relative_to(ROOT)): path.read_text() for folder in CHECKOUT
                for path in sorted((ROOT / folder).rglob('*'))
                if path.is_file() and (folder != str(fixture_copy.REGISTRY) or path.parent == ROOT / folder)}

    def setUp(self):
        super().setUp()
        self.forge = self.forge_class(self.origin)
        self.train = self.new_train()
        self.gate_port = forge_events.ForgeEvents(self.forge, self.clock, 'gate_report', 'run-1')
        self.lane_port = forge_events.ForgeEvents(self.forge, self.clock, 'pr-ready', 'lane-1')
        self.tier2_port = forge_events.ForgeEvents(self.forge, self.clock, config.get('forge-events.gate_producer'),
                                                   'tier2-run')

    def new_train(self):
        made = train.Train(self.forge, self.clock, self.workspace, self.gate, REPO)
        made.reuse.toolchain_id = lambda: TOOLCHAIN
        return made

    def batch(self, *specs):
        """PRs with `specs`, then the combined head the train builds for them: (base, member heads, combined)."""
        self.make(*specs)
        _, _, base, members, commits = self.train.start_batch(self.train.queue())
        return base, [entry.sha for entry in members], commits[-1]

    def proof(self, base, heads, commit, tier=None, pr=None, **changed):
        """The v4 gate.passed a tier-2 run of `commit` publishes (gate_proof.bind + proof_payload, the real producer),
        with `changed` binding inputs replaced and input_digest recomputed, so the proof is self-consistent."""
        plan = config.get('train-reuse.tier2_plan')
        selection = gate_batch.plan(self.work, base, heads, commit)['selection']
        binding = gate_proof.bind(self.work, ROOT, commit, base, plan, selection, toolchain_id=TOOLCHAIN)
        binding.update(changed)
        binding['input_digest'] = gate_digest.input_digest(*(binding[name] for name in gate_digest.FIELDS))
        verdict = dict(forge_events.subject(REPO, pr, commit), tier=tier or config.get('gate-tier.batch'),
                       plan=binding['plan'], stages=[], missing_stages=[],
                       input_hash=hashlib.sha256(commit.encode()).hexdigest())
        payload = gate_proof.proof_payload(verdict, {'stages': [], 'sha': commit}, binding, self.dir)
        return payload

    def publish(self, payload):
        return self.tier2_port.emit('gate.passed', payload, gate_proof.proof_version())

    def assert_runs(self, base, heads, commit):
        self.train.run_batch(self.train.queue())
        self.assertEqual(self.gate.runs, [commit], 'no exact verified proof: tier 2 runs')


class ToolingVersion(unittest.TestCase):
    def test_a_lookup_reads_its_toolings_version_once(self):
        """GATE-SPEED F3: one train run judges every batch with one tooling checkout, so its version is one git read."""
        with mock.patch.object(gate_proof, 'gate_version', return_value='tree') as read:
            lookup = train_reuse.Reuse(REPO, ROOT, ROOT, toolchain_id=lambda: TOOLCHAIN)
            self.assertEqual([lookup.gate_version() for _ in 'twice'], ['tree'] * len('twice'))
        read.assert_called_once_with(ROOT)


class ExactMatch(Reuse):
    def test_an_exact_verified_proof_is_the_verdict_and_nothing_runs(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'}, {'g.txt': 'y\n'})
        published = self.publish(self.proof(base, heads, commit))
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual(self.gate.runs, [], 'zero stage runs')
        self.assertEqual(len(merged), len(heads))
        self.assertEqual(list(self.train.verdicts.values()), [published['event_id']], 'the verdict names the proof')

    def test_rebuilding_an_unchanged_batch_runs_no_stage(self):
        """GX-30 rebuild: the first invocation runs tier 2 and halts before merging; the next rebuilds the same batch on
        the same tip and reuses the proof the first run published (as gate-batch publishes a tier-2 verdict)."""
        self.make({'f.txt': 'x\n'}, {'g.txt': 'y\n'})
        real = self.gate.run

        def run_and_publish(commit, env=None):
            result = real(commit, env)
            base, heads = env[train.BATCH_BASE_ENV], env[train.BATCH_MEMBERS_ENV].split()
            self.publish(self.proof(base, heads, commit))
            return result
        with mock.patch.object(self.gate, 'run', side_effect=run_and_publish), \
                mock.patch.object(train.Train, 'merge', side_effect=train.TrainHalt('lost the lock after tier 2')):
            with self.assertRaises(train.TrainHalt):
                self.train.run_batch(self.train.queue())
        self.assertEqual(len(self.gate.runs), 1)
        rebuilt = self.new_train()
        merged = rebuilt.run_batch(rebuilt.queue())
        self.assertEqual(len(self.gate.runs), 1, 'the rebuild of the unchanged batch ran no stage')
        self.assertEqual(len(merged), len(self.forge.merges))


class OneByteChange(Reuse):
    """A proof that differs from the judged run in one byte of exactly one input never stands in for it."""

    def check(self, **changed):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        exact = gate_proof.bind(self.work, ROOT, commit, base, config.get('train-reuse.tier2_plan'),
                                gate_batch.plan(self.work, base, heads, commit)['selection'], toolchain_id=TOOLCHAIN)
        self.publish(self.proof(base, heads, commit, **{name: one_byte(exact[name]) for name in changed}))
        self.assert_runs(base, heads, commit)

    def test_head_tree(self):
        self.check(head_tree=True)

    def test_base(self):
        self.check(base_sha=True)

    def test_plan(self):
        self.check(plan=True)

    def test_selection(self):
        self.check(selection_digest=True)

    def test_toolchain_id(self):
        self.check(toolchain_id=True)

    def test_gate_version(self):
        self.check(gate_version=True)

    def test_a_one_byte_content_change_of_a_member_runs(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit))
        number = self.forge.open[0]
        changed = self.pr(number, {'f.txt': 'y\n'})
        self.assertNotEqual(changed, heads[0])
        self.train.run_batch(self.train.queue())
        self.assertEqual(len(self.gate.runs), 1, 'the new tree is not proven by the old proof')
        self.assertNotEqual(self.gate.runs[0], commit)


class FailClosed(Reuse):
    def test_an_untrusted_author_is_never_read(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.forge.author = 'NONE'
        self.assertNotIn(self.forge.author, self.forge.trusted)
        self.publish(self.proof(base, heads, commit))
        self.assert_runs(base, heads, commit)

    def test_an_event_whose_id_does_not_verify_is_never_read(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        envelope = self.tier2_port.build('gate.passed', self.proof(base, heads, commit), gate_proof.proof_version())
        envelope['event_id'] = one_byte(envelope['event_id'])
        self.forge.append(forge_events.Channel(REPO, None), [envelope])
        self.assert_runs(base, heads, commit)

    def test_a_tier_1_or_pr_channel_proof_is_never_reused(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit, tier=config.get('gate-tier.per_pr')))
        self.publish(self.proof(base, heads, commit, pr=self.forge.open[0]))
        self.assert_runs(base, heads, commit)

    def test_an_unattested_toolchain_runs(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit))

        def unattested():
            raise RuntimeError('toolchain not attested')
        self.train.reuse.toolchain_id = unattested
        self.assert_runs(base, heads, commit)

    def test_a_reuse_check_on_another_commit_runs(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit))
        found, reason = self.train.reuse.find(self.tier2_port, base, heads, base)
        self.assertIsNone(found, reason)


class BoxLocal(Reuse):
    """A log on this box (the file log of forge-events.file_kinds, an in-memory log) is never a source."""

    forge_class = FakeForge

    def test_a_matching_proof_in_a_local_log_runs(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit))
        self.assertIsNone(train_reuse.verified_source(self.forge))
        self.assert_runs(base, heads, commit)


class Switch(Reuse):
    def test_reuse_is_on_by_default(self):
        self.assertIs(train_reuse.enabled(), True)
        self.assertIs(config.get(SWITCH), True)

    def test_off_restores_todays_tier_2_exactly(self):
        base, heads, commit = self.batch({'f.txt': 'x\n'})
        self.publish(self.proof(base, heads, commit))
        with config.use_adapter(forge_events.MemoryAdapter()):
            config.set_value(SWITCH, False, actor='gx31-test', reason='rollback', now=self.clock.now())
            self.assertIs(train_reuse.enabled(), False)
            with mock.patch.object(train_reuse.Reuse, 'find') as find:
                self.assert_runs(base, heads, commit)
            find.assert_not_called()


if __name__ == '__main__':
    unittest.main()
