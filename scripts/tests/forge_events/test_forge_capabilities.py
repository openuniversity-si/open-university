"""Every construction validates its own provider without changing selection."""
from pathlib import Path
import sys
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / 'lib'))
import config
import forge_events as events
import operation_demands
import push_guard


class Partial:
    remote = False


class Journal(Partial):
    def append(self, *args):
        raise AssertionError('construction must not append')

    def read(self, *args):
        raise AssertionError('construction must not read')


class Capabilities(unittest.TestCase):
    def test_direct_change_and_router_name_responsible_provider(self):
        for adapter in (Partial(), events.RoutingAdapter(Partial(), {}, default=Journal())):
            with self.subTest(adapter=type(adapter).__name__):
                with mock.patch.object(events, '_require_compatibility'), self.assertRaisesRegex(events.ForgeCompatibilityError, 'Partial.*change'):
                    events.ForgeEvents(adapter, events.SystemClock(), 'test', 'test',
                                       consumer='scripts/lib/gate_report.py')

    def test_board_comments_refused_before_issue_comments(self):
        values = {'forge-events.adapter': 'github', 'forge-events.repo': 'o/r'}
        with mock.patch.dict(events.ADAPTERS, github=Partial), \
                mock.patch.object(config, 'get', side_effect=values.__getitem__):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'board comments.*Partial.*issue_comments'):
                events.board_adapter(1)

    def test_board_comments_come_from_the_selected_forge(self):
        # ORIGIN-FINISH R2: the board never names a forge; with origin selected, github is not built
        built = []

        def named(name):
            def make():
                built.append(name)
                return Partial()
            return make
        values = {'forge-events.adapter': 'origin', 'forge-events.repo': 'o/r'}
        with mock.patch.dict(events.ADAPTERS, github=named('github'), origin=named('origin')), \
                mock.patch.object(config, 'get', side_effect=values.__getitem__):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'board comments.*Partial.*issue_comments'):
                events.board_adapter(1)
        self.assertEqual(built, ['origin'])

    def configured(self, **overrides):
        values = {'forge-events.adapter': 'github', 'forge-events.file_kinds': [],
                  'forge-events.board_issue': 0, 'forge-events.log_adapter': 'control'}
        values.update(overrides)
        return mock.patch.object(config, 'get', side_effect=values.__getitem__)

    def test_main_is_checked_when_it_also_serves_the_journal(self):
        with self.configured(**{'forge-events.log_adapter': 'github'}), mock.patch.dict(events.ADAPTERS, github=Partial):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'main journal.*Partial.*append'):
                events.adapter_from_config()

    def test_default_journal_construction(self):
        with self.configured(), mock.patch.dict(events.ADAPTERS, github=Journal, control=Partial):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'default journal.*Partial.*append'):
                events.adapter_from_config()

    def test_file_route_construction(self):
        with self.configured(**{'forge-events.file_kinds': ['gate.passed']}):
            with mock.patch.dict(events.ADAPTERS, github=Journal, file=Partial):
                with self.assertRaisesRegex(events.ForgeCompatibilityError, 'file kinds journal.*Partial.*append'):
                    events.adapter_from_config()

    def test_main_file_construction(self):
        with self.configured(**{'forge-events.adapter': 'file'}), mock.patch.dict(events.ADAPTERS, file=Partial):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'configured forge.*Partial.*append'):
                events.adapter_from_config()

    def test_config_store_construction(self):
        # D-300: the file store is the only one, so the store's own adapter is checked at construction
        with mock.patch.object(events, 'FileAdapter', lambda _path: Partial()):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'config store.*Partial.*append'):
                config.store()

    def test_heartbeat_construction(self):
        result = mock.Mock(status='pushed')
        with mock.patch.object(config, 'get', return_value='github'), mock.patch.dict(events.ADAPTERS, github=Partial):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'push heartbeat.*Partial.*append'):
                push_guard.heartbeat(result, '.')

    def test_router_rejects_partial_route_at_construction(self):
        with self.assertRaisesRegex(events.ForgeCompatibilityError, 'routing journal.*Partial.*append'):
            events.RoutingAdapter(Journal(), {'event': Partial()})


if __name__ == '__main__':
    unittest.main()
