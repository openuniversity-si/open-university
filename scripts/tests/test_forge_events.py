"""forge_events port (D-065, M2; D-069 items 4-6): versioned, idempotent, replayable. Fake adapter and clock."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
import json
import tempfile
import contextlib
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402

REPO = config.get('forge-events.repo')  # the code under test reads the same key; a literal went stale with the move to Origin
HEAD, NEXT, MERGE = 'a' * 40, 'b' * 40, 'c' * 40


class FakeClock:
    def __init__(self, start=datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc), step=timedelta(seconds=1)):
        self.moment, self.step = start, step

    def now(self):
        current = self.moment
        self.moment += self.step
        return current


def gate(verdict, sha=HEAD, plan='dev', pr=7):
    payload = forge_events.subject(REPO, pr, sha, ['P-02'])
    payload.update({'tier': 1, 'plan': plan, 'missing_stages': [], 'input_hash': 'd' * 64,
                    'stages': [{'name': 'lint', 'result': 'PASS' if verdict == 'passed' else 'FAIL',
                                'duration_ms': 1200, 'class': None if verdict == 'passed' else 'code'}]})
    return f'gate.{verdict}', payload


def port(adapter=None, clock=None, producer='gate_report', correlation='run-1'):
    return forge_events.ForgeEvents(adapter or forge_events.MemoryAdapter(), clock or FakeClock(), producer, correlation)


# A schema gains versions over time (expand, never rewrite): tests name the newest one from the catalog, never a literal.
LATEST = {kind: max(versions) for kind, versions in event_contracts.catalog().items()}


class Boundary(unittest.TestCase):
    def test_the_port_never_touches_the_vendor(self):
        source = (ROOT / 'scripts' / 'lib' / 'forge_events.py').read_text()
        self.assertNotIn('github_api', source)
        # D-293: the GitHub adapter left the port; no factory, readiness loader or selection names its module
        self.assertNotIn('forge_github', source)
        self.assertNotIn('github', set(forge_events.ADAPTERS) | set(forge_events.READINESS))
        # the vendor modules that remain load lazily, by name, one factory each
        origin = [name for name in forge_events.DYNAMIC_IMPORTS if name.startswith('_origin')]
        self.assertEqual(source.count("import_module('forge_origin')"), len(origin), 'the Origin adapter and its readiness')
        for kind, versions in event_contracts.catalog().items():
            for name in versions.values():
                self.assertNotIn('github', (event_contracts.directory() / name).read_text().lower(), name)


class Subject(unittest.TestCase):
    def test_premises_from_body(self):
        body = 'x\nCapability: CAP-011\nPremises: P-02, P-34, P-32, P-07, P-02\nFit-Review: not reviewed'
        self.assertEqual(forge_events.premises_from_body(body), ['P-02', 'P-34', 'P-32', 'P-07'])
        self.assertEqual(forge_events.premises_from_body('no line'), [])
        self.assertEqual(forge_events.premises_from_body(None), [])


PR = 1
EXPECTED_OPERATIONS = frozenset(
    'approvals calls change closed_changes change_commits change_files commit_files compare force_pushes close_change comment comments find_change lock merge open_change '
    'open_changes open_pulls pull pushes set_status unlock upsert_comment'.split())
EXPECTED_CONSUMERS = frozenset('scripts/lib/' + name + '.py' for name in (
    'defect_router engine_role service_lock flow_check gate_report gate_status lessons pr_ready prepush replay_branch '
    'stall_report train train_box train_queue train_verdict premises structure forge_pr gate_policy idea_to_prod '
    'gate_pin gate_explain merge_behind decision_next service_runner'.split()))


class MemoryEvidence(unittest.TestCase):
    def test_change_copies_the_requested_metadata(self):
        adapter = forge_events.MemoryAdapter({(REPO, PR): {'head': HEAD, 'base': NEXT, 'body': 'body'}})
        found = adapter.change(REPO, PR)
        self.assertEqual(found, {'head': HEAD, 'base': NEXT, 'body': 'body'})
        found['body'] = 'modified'
        self.assertEqual(adapter.change(REPO, PR)['body'], 'body')
        with self.assertRaises(forge_events.ForgeEventsError):
            adapter.change(REPO, PR + 1)

    def test_status_preserves_all_fields(self):
        adapter = forge_events.MemoryAdapter()
        url = 'local-report'
        adapter.set_status(REPO, HEAD, 'tower/gate', 'pending', 'running', url)
        self.assertEqual(adapter.statuses, [dict(repo=REPO, sha=HEAD, context='tower/gate', state='pending',
                                               description='running', url=url)])


class CallerOrigins(unittest.TestCase):
    def fixture(self):
        import operation_demands
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in ('a', 'b'):
            (root / name).mkdir()
            (root / name / 'consumer.py').write_text('source')
        declaration = root / 'scripts/lib/operation_demands.json'
        declaration.parent.mkdir(parents=True)
        declaration.write_text(json.dumps({'consumers': {'a/consumer.py': ['pull'], 'b/consumer.py': ['pull']},
                                           'proofs': {}}))
        return root, operation_demands

    @staticmethod
    def function(filename, root, demands):
        namespace = {'root': root, 'demands': demands}
        exec(compile('def invoke():\n    return demands.callers(root)\n', str(filename), 'exec'), namespace)
        return namespace['invoke']

    def test_loaded_code_keeps_its_observed_origin_and_new_code_resolves_again(self):
        root, demands = self.fixture()
        link = root / 'alias'
        link.symlink_to(root / 'a', target_is_directory=True)
        loaded = self.function(link / 'consumer.py', root, demands)
        self.assertEqual(loaded()[0], 'a/consumer.py')
        link.unlink()
        link.symlink_to(root / 'b', target_is_directory=True)
        self.assertEqual(loaded()[0], 'a/consumer.py')
        fresh = self.function(link / 'consumer.py', root, demands)
        self.assertEqual(fresh()[0], 'b/consumer.py')

    def test_relative_synthetic_code_still_resolves_in_its_current_directory(self):
        root, demands = self.fixture()
        loaded = self.function('consumer.py', root, demands)
        for name in ('a', 'b'):
            with contextlib.chdir(root / name):
                self.assertEqual(loaded()[0], f'{name}/consumer.py')


class Compatibility(unittest.TestCase):
    def setUp(self):
        import operation_demands
        import operation_demands_check
        self.demands = operation_demands
        self.check = operation_demands_check  # D-322: the confrontation with the tree left the events layer

    def test_declared_demands_and_proofs_match_the_tree(self):
        self.assertEqual(self.check.confront(), [])
        document = self.demands.load()
        self.assertEqual(set(document['consumers']), EXPECTED_CONSUMERS)
        self.assertEqual({op for ops in document['consumers'].values() for op in ops}, EXPECTED_OPERATIONS)
        self.assertNotIn('github', document['proofs'])
        self.assertTrue(self.demands.refusals('github', document['consumers']))
        # Origin's push history is proven (ORIGIN-PUSH-HISTORY): no consumer demand is refused for origin.
        self.assertEqual(self.demands.refusals('origin', document['consumers']), [])

    def test_method_presence_does_not_authorize_an_unproven_operation(self):
        adapter = forge_events.FileAdapter('/unused')
        self.assertTrue(callable(adapter.change))
        with self.assertRaisesRegex(forge_events.ForgeEventsError, 'operation change, adapter file, demand'):
            port(adapter).change(REPO, PR)

    def test_unknown_adapter_cannot_authorize_its_own_method(self):
        class Unproven:
            def comment(self, *args):
                raise AssertionError('effect must not start')
        with self.assertRaisesRegex(forge_events.ForgeEventsError, 'operation comment, adapter unknown:'):
            port(Unproven()).comment(REPO, PR, 'body')

    def test_direct_change_has_the_same_named_refusal_without_changing_the_census(self):
        import operation_relations
        self.assertEqual(operation_relations.surface()['change'], 'direct')
        self.assertEqual(set(operation_relations.surface()), EXPECTED_OPERATIONS)
        with self.assertRaisesRegex(forge_events.ForgeEventsError, 'operation change, adapter unknown:'):
            port(object()).change(REPO, PR)

    def test_partial_adapter_is_valid_for_a_compatible_consumer(self):
        import forge_origin
        adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        with mock.patch.object(adapter, 'comments', return_value=[{'body': 'local'}]) as read:
            events = forge_events.ForgeEvents(adapter, FakeClock(), 'test', 'partial',
                                             consumer='scripts/lib/lessons.py')
            self.assertEqual(events.comments(REPO, PR), [{'body': 'local'}])
            read.assert_called_once_with(REPO, PR)

    def test_routing_uses_main_forge_evidence_instead_of_the_journal(self):
        import forge_origin
        main = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        routed = forge_events.RoutingAdapter(main, {}, default=forge_events.MemoryAdapter())
        answer = [{'before': 'a' * 40, 'after': 'b' * 40, 'timestamp': 't'}]
        with mock.patch.object(main, 'pushes', return_value=answer) as read:
            events = forge_events.ForgeEvents(routed, FakeClock(), 'test', 'routing',
                                              consumer='scripts/lib/stall_report.py')
            self.assertEqual(events.pushes(REPO, 'feature'), answer)
        read.assert_called_once_with(REPO, 'feature')  # the main adapter answers, not the journal default

    def fixture(self, root):
        # Independent oracle: this source always writes first, then needs history.
        # It is NOT generated from the declared demand or proof table.
        source = """def run(port):
    port.comment('o/r', 1, 'effect')
    port.pushes('o/r', 'topic')
"""
        path = root / 'scripts/lib/local_batch.py'
        path.parent.mkdir(parents=True)
        path.write_text(source)
        evidence = root / 'scripts/tests/forge_events/test_forge_contract.py'
        evidence.parent.mkdir(parents=True)
        evidence.write_text((ROOT / 'scripts/tests/forge_events/test_forge_contract.py').read_text())
        document = {'consumers': {'scripts/lib/local_batch.py': ['comment', 'pushes']},
                    'proofs': {'origin': {'comment':
                        'scripts/tests/forge_events/test_forge_contract.py::OriginContract::'
                        'test_comment_append_and_list_preserve_text_and_order'}}, 'unknowns': []}
        namespace = {}
        exec(compile(source, str(path), 'exec'), namespace)
        return document, namespace['run']

    def test_whole_demand_refuses_before_first_effect_on_a_reused_port(self):
        import forge_origin
        adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        events = port(adapter)
        effects = []
        adapter.__dict__['pushes'] = mock.Mock(return_value=[])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document, run = self.fixture(root)
            with (mock.patch.object(self.demands, 'ROOT', root),
                  mock.patch.object(self.demands, 'load', return_value=document),
                  mock.patch.object(adapter, 'comment', side_effect=lambda *a: effects.append(a))):
                with self.assertRaisesRegex(forge_events.ForgeEventsError,
                                            'operation pushes, adapter origin, demand scripts/lib/local_batch.py'):
                    run(events)
            self.assertEqual(effects, [], 'the first write, not just the missing call, must never run')

    def test_factory_refuses_before_constructing_any_adapter_or_board(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document, _ = self.fixture(root)
            source = "def run():\n    return forge_events.adapter_from_config()\n"
            namespace = {'forge_events': forge_events}
            exec(compile(source, str(root / 'scripts/lib/local_batch.py'), 'exec'), namespace)
            with (mock.patch.object(self.demands, 'ROOT', root),
                  mock.patch.object(self.demands, 'load', return_value=document),
                  mock.patch.object(forge_events.config, 'get', return_value='origin'),
                  mock.patch.dict(forge_events.ADAPTERS, {'origin': mock.Mock()}),
                  mock.patch.object(forge_events, 'board_adapter') as board):
                factory = forge_events.ADAPTERS['origin']
                with self.assertRaisesRegex(forge_events.ForgeEventsError, 'operation pushes, adapter origin'):
                    namespace['run']()
                factory.assert_not_called()
                board.assert_not_called()

    def test_static_difference_is_exposed_and_unknown_consumers_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document, _ = self.fixture(root)
            # A minimal independent port surface for the existing AST extractor.
            (root / 'scripts/lib/forge_events.py').write_text(
                "class ForgeEvents:\n    def comment(self): self._operation('comment')\n"
                "    def pushes(self): self._operation('pushes')\n")
            document['consumers']['scripts/lib/local_batch.py'] = ['comment']
            document['consumers']['scripts/lib/dynamic.py'] = ['pushes']
            document['proofs'] = {}
            with mock.patch.object(self.demands, 'load', return_value=document):
                findings = self.check.confront(root)
            self.assertIn(('undeclared-demand', 'scripts/lib/local_batch.py: pushes'), findings)
            self.assertIn(('unknown-demand', 'scripts/lib/dynamic.py: pushes; static extraction cannot confirm it'),
                          findings)

    def test_caller_outside_the_scanned_tree_is_an_explicit_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(self.demands, 'ROOT', Path(directory)):
                callers = self.demands.callers()
        self.assertTrue(callers)
        self.assertTrue(callers[0].startswith('unknown consumer: '))
        self.assertIn('test_forge_events.py', callers[0])

    def test_proof_reference_must_resolve_to_a_test_of_that_operation(self):
        document = json.loads((ROOT / self.demands.DECLARATION).read_text())
        document['proofs']['origin']['pushes'] = document['proofs']['origin']['comment']
        with mock.patch.object(self.demands, 'load', return_value=document):
            kinds = [kind for kind, _ in self.check.confront()]
        with mock.patch.object(self.demands, 'load', return_value=document):
            with self.assertRaisesRegex(self.demands.CompatibilityError, 'operation pushes, adapter origin'):
                self.demands.require('origin', ['scripts/lib/stall_report.py'])
        self.assertIn('unknown-proof', kinds)
        # origin implements pushes, so a proof that does not call it is unknown, not unimplemented.
        self.assertNotIn('unimplemented-proof', kinds)
        document['proofs']['origin']['no_such_operation'] = document['proofs']['origin']['comment']
        with mock.patch.object(self.demands, 'load', return_value=document):
            kinds = [kind for kind, _ in self.check.confront()]
        self.assertIn('unimplemented-proof', kinds)


if __name__ == '__main__':
    unittest.main(verbosity=1)
