"""Verdict admission (D-075, P-53): train_admit.admissible, one test per refusal and the admitted case. Pure: no git,
no network; the proof is a gate.passed envelope built here with the digest the train recomputes."""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import config  # noqa: E402
import gate_digest  # noqa: E402
import gate_proof  # noqa: E402
import train_admit  # noqa: E402


def sha(label):
    """A git-shaped object id named by `label`."""
    return hashlib.sha1(label.encode()).hexdigest()


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


PLAN, VERSION = 'dev', gate_proof.proof_version()
TIP, HEAD, TREE, GATE = sha('tip'), sha('head'), sha('head tree'), sha('tip scripts tree')
TOOLCHAIN = digest('attested toolchain')
STAGES = [{'name': 'unit tests', 'result': 'PASS', 'cached': False}]


def proof(**changes):
    """A cold, verified v4 proof of HEAD on TIP; `changes` overrides payload fields (None deletes one)."""
    payload = {'sha': HEAD, 'plan': PLAN, 'base_sha': TIP, 'head_tree': TREE, 'toolchain_id': TOOLCHAIN,
               'gate_version': GATE, 'tier': 1,
               'input_digest': gate_digest.input_digest(TREE, TIP, PLAN, gate_proof.selection_digest(PLAN, None),
                                                        TOOLCHAIN, GATE),
               'stages': STAGES,
               'cost': {'cache_hits': 0, 'cache_misses': len(STAGES)}}
    for name, value in changes.items():
        if value is None:
            payload.pop(name, None)
        else:
            payload[name] = value
    return {'type': 'gate.passed', 'version': VERSION, 'event_id': digest('verdict'), 'payload': payload}


def judge(event, **changes):
    call = dict(proof=event, tip=TIP, head=HEAD, head_tree=TREE, contains_tip=True, toolchain_id=TOOLCHAIN,
                gate_version=GATE, plan=PLAN, version=VERSION, verified=True)
    call.update(changes)
    return train_admit.admissible(**call)


class Admissible(unittest.TestCase):
    def refused(self, result, words):
        ok, reason = result
        self.assertFalse(ok)
        self.assertIn(words, reason)

    def test_a_cold_exact_verdict_on_the_tip_is_admitted_with_its_recomputed_digest(self):
        self.assertEqual(judge(proof()), (True, proof()['payload']['input_digest']))

    def test_an_unverified_source_is_refused(self):
        self.refused(judge(proof(), verified=False), 'verified source')

    def test_another_event_type_is_refused(self):
        self.refused(judge(dict(proof(), type='gate.failed')), 'not a gate.passed')

    def test_a_bypassed_verdict_with_no_proof_is_refused_as_the_973_merge_would_be(self):
        # D-259: a bypassed gate binds no v4 proof, so the evidence is no proof the train can admit.
        self.refused(judge(None), 'not a gate.passed')

    def test_a_v3_verdict_is_refused(self):
        self.refused(judge(dict(proof(), version=VERSION - 1)), f'proof version {VERSION - 1}')

    def test_another_plan_is_refused(self):
        self.refused(judge(proof(plan='quiet')), 'plan quiet')

    def test_a_proof_of_another_head_is_refused(self):
        self.refused(judge(proof(sha=sha('other head'))), 'not the head')

    def test_a_base_that_is_not_the_tip_is_refused(self):
        self.refused(judge(proof(base_sha=sha('old tip'))), 'not the tip')

    def test_a_head_that_does_not_contain_the_tip_is_refused(self):
        self.refused(judge(proof(), contains_tip=False), 'does not contain the tip')

    def test_another_toolchain_is_refused(self):
        self.refused(judge(proof(toolchain_id=digest('other image'))), 'not the attested')

    def test_another_gate_version_is_refused(self):
        self.refused(judge(proof(gate_version=sha('other gate'))), 'not the tip gate')

    def test_a_recorded_tree_that_is_not_the_head_tree_is_refused(self):
        self.refused(judge(proof(head_tree=sha('other tree'))), 'not the head tree')

    def test_a_recorded_digest_that_differs_from_the_recomputed_one_is_refused(self):
        self.refused(judge(proof(input_digest=digest('recorded'))), 'not the recomputed')

    def test_a_pr_gate_digest_with_a_batch_selection_is_refused(self):
        batch = gate_digest.input_digest(TREE, TIP, PLAN, gate_proof.selection_digest(PLAN, {'units': []}), TOOLCHAIN,
                                         GATE)
        self.refused(judge(proof(input_digest=batch)), 'not the recomputed')

    def test_cache_hits_are_refused(self):
        self.refused(judge(proof(cost={'cache_hits': len(STAGES), 'cache_misses': 0})), f'cache_hits {len(STAGES)}')

    def test_a_missing_cost_is_refused(self):
        self.refused(judge(proof(cost=None)), 'cache_hits None')

    def test_a_carried_verdict_is_refused(self):
        self.refused(judge(proof(carried_from={'event_id': 'x', 'sha': sha('earlier head'), 'delta_files': []})), 'carried from')

    def test_cached_tests_are_refused(self):
        self.refused(judge(proof(cached_tests=[{'key': 'k', 'source': 's'}])), '1 cached test')

    def test_a_cached_stage_is_refused(self):
        self.refused(judge(proof(stages=[{'name': 'lint', 'result': 'PASS', 'cached': True}])), 'cached stage(s) lint')

    def test_hits_reused_by_content_are_admitted(self):
        """D-076 (P-56): the tip's tooling keys every cached test and stage by content: its hits are this tree's."""
        warm = proof(cost={'cache_hits': len(STAGES), 'cache_misses': 1},
                     cached_tests=[{'key': 'k', 'source': 's'}],
                     stages=[{'name': 'lint', 'result': 'PASS', 'cached': True}])
        self.assertEqual(judge(warm, content=True), (True, warm['payload']['input_digest']))

    def test_content_hits_are_refused_when_the_train_has_the_content_cache_off(self):
        warm = proof(cost={'cache_hits': 1, 'cache_misses': 0})
        self.refused(judge(warm, content=False), 'cache_hits 1')

    def test_a_carried_verdict_is_refused_even_in_content_mode(self):
        carried = proof(carried_from={'event_id': 'x', 'sha': sha('earlier'), 'delta_files': []})
        self.refused(judge(carried, content=True), 'carried from')

    def test_a_missing_input_is_refused_never_raised(self):
        self.refused(judge(proof(), toolchain_id=''), 'toolchain')
        self.refused(judge(proof(toolchain_id=''), toolchain_id=''), 'toolchain_id must be a non-empty string')



OLD = sha('verdict base')
MANIFESTS = [{'id': 'catalog', 'paths': ['products/demo/src/catalog/**']},
             {'id': 'media', 'paths': ['products/demo/src/media/**'], 'requires': {'kernel': '^1'}},
             {'id': 'kernel', 'paths': ['products/demo/src/kernel/**']}]
NEVER = config.get('train.shard_admit_never')
MAX_BEHIND = config.get('train.shard_admit_max_behind')


def behind_proof():
    """A cold verdict on the older tip OLD, its digest recomputed with OLD (the base the gate judged)."""
    return proof(base_sha=OLD, input_digest=gate_digest.input_digest(TREE, OLD, PLAN,
                                                                     gate_proof.selection_digest(PLAN, None),
                                                                     TOOLCHAIN, GATE))


def disjoint(pr_files, base_files, distance=1):
    return train_admit.disjoint(MANIFESTS, pr_files, base_files, distance, MAX_BEHIND, NEVER)


class ShardAdmission(unittest.TestCase):
    """P-54: a verdict on an older tip admits when the two changes cannot touch each other; one refusal each."""

    def shard(self, collision='', base_in_head=True, base_in_tip=True):
        return train_admit.Shard(base_in_head, base_in_tip, collision)

    def test_a_disjoint_verdict_behind_the_tip_is_admitted_with_the_digest_of_its_own_base(self):
        found = judge(behind_proof(), contains_tip=False, shard=self.shard())
        self.assertEqual(found, (True, behind_proof()['payload']['input_digest']))

    def test_without_a_shard_a_verdict_behind_the_tip_stays_refused(self):
        self.assertFalse(judge(behind_proof())[0])

    def test_a_head_without_its_verdict_base_is_refused(self):
        ok, reason = judge(behind_proof(), shard=self.shard(base_in_head=False))
        self.assertEqual((ok, reason), (False, f'the head does not contain its verdict base {OLD}'))

    def test_a_verdict_base_off_the_tip_history_is_refused(self):
        ok, reason = judge(behind_proof(), shard=self.shard(base_in_tip=False))
        self.assertFalse(ok)
        self.assertIn('not an ancestor of the tip', reason)

    def test_a_collision_is_refused_with_its_reason(self):
        self.assertEqual(judge(behind_proof(), shard=self.shard('overlap on unit:media')),
                         (False, 'shard: overlap on unit:media'))

    def test_the_digest_recorded_against_the_tip_does_not_admit_a_verdict_on_an_older_base(self):
        ok, reason = judge(proof(base_sha=OLD), shard=self.shard())
        self.assertFalse(ok)
        self.assertIn('not the recomputed', reason)

    def test_a_warm_verdict_behind_the_tip_is_still_refused(self):
        warm = behind_proof()
        warm['payload']['cost'] = {'cache_hits': len(STAGES), 'cache_misses': 0}
        self.assertFalse(judge(warm, shard=self.shard())[0])


HEAD_TOOLCHAIN = digest('the head\'s own toolchain')


def foreign_proof(**changes):
    """The pinned gate's cold verdict of a PR that changes the toolchain: its toolchain_id is the head's own."""
    fields = dict(toolchain_id=HEAD_TOOLCHAIN,
                  input_digest=gate_digest.input_digest(TREE, TIP, PLAN, gate_proof.selection_digest(PLAN, None),
                                                        HEAD_TOOLCHAIN, GATE))
    return proof(**{**fields, **changes})


class SelfHosting(unittest.TestCase):
    """D-079 (TRAIN-ADMIT-GATE-CHANGE): a toolchain-changing PR admits on the dual verdict, never on one leg."""

    def leg(self, passed, why='exit 0'):
        self.calls = []
        return train_admit.SelfHost(['scripts/lib/gate_keys.py'],
                                    lambda: self.calls.append(HEAD) or (passed, why))

    def test_a_gate_changing_pr_is_admitted_on_dual_green_with_the_digest_of_its_own_toolchain(self):
        event = foreign_proof()
        self.assertEqual(judge(event, self_host=self.leg(True)), (True, event['payload']['input_digest']))
        self.assertEqual(self.calls, [HEAD])

    def test_a_red_head_toolchain_leg_is_refused(self):
        ok, reason = judge(foreign_proof(), self_host=self.leg(False, 'exit 1'))
        self.assertFalse(ok)
        self.assertIn('dual verdict', reason)
        self.assertIn('exit 1', reason)

    def test_a_red_pinned_leg_is_refused_without_running_the_head_leg(self):
        """The proof is a gate.passed: a red pinned gate leaves no proof, and any strict defect refuses first."""
        for event, words in ((dict(foreign_proof(), type='gate.failed'), 'not a gate.passed'),
                             (foreign_proof(cost={'cache_hits': len(STAGES)}), 'not cold'),
                             (foreign_proof(gate_version=sha('head scripts tree')), 'gate_version'),
                             (foreign_proof(input_digest=digest('forged')), 'input_digest')):
            ok, reason = judge(event, self_host=self.leg(True))
            self.assertFalse(ok)
            self.assertIn(words, reason)
            self.assertEqual(self.calls, [])

    def test_a_pr_that_touches_no_toolchain_path_keeps_the_strict_refusal(self):
        leg = train_admit.SelfHost([], lambda: self.fail('the head leg ran for a PR that changes no toolchain path'))
        ok, reason = judge(foreign_proof(), self_host=leg)
        self.assertFalse(ok)
        self.assertIn(f'toolchain {HEAD_TOOLCHAIN} is not the attested {TOOLCHAIN}', reason)

    def test_a_non_gate_pr_is_unchanged(self):
        self.assertEqual(judge(proof(), self_host=self.leg(False)), (True, proof()['payload']['input_digest']))
        self.assertEqual(self.calls, [])

    def test_a_foreign_toolchain_behind_the_tip_is_never_self_hosted(self):
        shard = train_admit.Shard(True, True, '')
        ok, reason = judge(foreign_proof(base_sha=sha('old tip')), self_host=self.leg(True), shard=shard)
        self.assertFalse(ok)
        self.assertIn('is not the attested', reason)


class Disjoint(unittest.TestCase):
    def test_changes_in_unrelated_units_are_disjoint(self):
        self.assertEqual(disjoint(['products/demo/src/catalog/a.ts'], ['products/demo/src/media/b.ts']), '')

    def test_the_same_unit_overlaps(self):
        self.assertEqual(disjoint(['products/demo/src/media/a.ts'], ['products/demo/src/media/b.ts']), 'overlap on unit:media')

    def test_a_dependent_unit_overlaps(self):
        found = disjoint(['products/demo/src/media/a.ts'], ['products/demo/src/kernel/b.ts'])
        self.assertEqual(found, 'overlap on unit:media', 'media requires kernel: a kernel change reaches it')

    def test_the_same_unclaimed_path_overlaps(self):
        self.assertEqual(disjoint(['README.md'], ['README.md']), 'overlap on path:README.md')

    def test_a_generated_output_is_not_skipped(self):
        self.assertEqual(disjoint(['CODEOWNERS'], ['CODEOWNERS']), 'overlap on path:CODEOWNERS')

    def test_a_never_path_on_the_pr_refuses(self):
        self.assertEqual(disjoint(['config/registry/train.json'], ['products/demo/src/media/b.ts']),
                         'the PR changes config/registry/train.json, a train.shard_admit_never path')

    def test_a_never_path_on_the_base_refuses(self):
        found = disjoint(['products/demo/src/catalog/a.ts'], ['units/media/unit.json'])
        self.assertEqual(found, 'the base changes units/media/unit.json, a train.shard_admit_never path')

    def test_a_gate_change_on_the_base_refuses(self):
        self.assertIn('scripts/lib/gate_proof.py', disjoint(['products/demo/src/catalog/a.ts'], ['scripts/lib/gate_proof.py']))

    def test_too_far_behind_refuses(self):
        found = disjoint(['products/demo/src/catalog/a.ts'], ['products/demo/src/media/b.ts'], MAX_BEHIND + 1)
        self.assertEqual(found, f'the tip is {MAX_BEHIND + 1} merges past the verdict base '
                                f'(train.shard_admit_max_behind {MAX_BEHIND})')

    def test_the_limit_itself_is_allowed(self):
        self.assertEqual(disjoint(['products/demo/src/catalog/a.ts'], ['products/demo/src/media/b.ts'], MAX_BEHIND), '')

if __name__ == '__main__':
    unittest.main()
