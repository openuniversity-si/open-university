"""BRANCH-MERGE (docs/operations/aws.md 22.9): the base merged into a unit's branch and pushed by the live service with the
forge's key, in a clone of its own; the delivery follows it with a fast-forward. Against a bare forge on the disk; the SQL
class needs TEST_DATABASE_URL (skipped without)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import branches, container, http_port  # noqa: E402
import deliver  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
REPO = branches.REPO


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class Forge:
    def __init__(self, root):
        self.root, self.bare, self.work = root, root / 'forge' / f'{REPO}.git', root / 'work'
        self.bare.parent.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'mod/base', str(self.bare)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.bare), str(self.work)], check=True, capture_output=True)
        self.commit('mod/base', {'a.txt': 'a\n'})

    def url(self):
        return f'file://{self.root}/forge'

    def commit(self, branch, files):
        exists = subprocess.run(['git', '-C', str(self.work), 'rev-parse', '--verify', '-q', f'origin/{branch}'],
                                capture_output=True).returncode == 0
        git(self.work, 'checkout', '-q', '-B', branch, *([f'origin/{branch}'] if exists else []))
        for name, text in files.items():
            (self.work / name).write_text(text)
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', f'{branch}: {sorted(files)}')
        git(self.work, 'push', '-q', 'origin', f'HEAD:refs/heads/{branch}')
        git(self.work, 'fetch', '-q', 'origin')
        return git(self.work, 'rev-parse', 'HEAD')

    def tip(self, branch):
        return git(self.bare, 'rev-parse', f'refs/heads/{branch}')


class TheMerger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.forge = Forge(self.tmp)
        environ = {k: v for k, v in os.environ.items() if k not in ('CURSOR_API_KEY', 'CURSOR_AUTH_TOKEN')}
        self.box = container.Container(self.tmp / 'service', forge_url=self.forge.url(), slot=branches.SLOT, environ=environ)
        self.merger = branches.Merger(self.box)

    def asked(self, head, branch='units/x'):
        return {'id': '1', 'state': 'asked', 'branch': branch, 'head': head, 'base': 'mod/base'}

    def test_a_branch_behind_its_base_gets_the_merge_pushed_and_one_with_it_is_current(self):
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        self.assertEqual(self.merger.merge(self.asked(head)), ('current', {'sha': head}))
        moved_base = self.forge.commit('mod/base', {'c.txt': 'c\n'})
        outcome, said = self.merger.merge(self.asked(head))
        self.assertEqual((outcome, self.forge.tip('units/x')), ('merged', said['sha']))
        parents = git(self.forge.bare, 'log', '-1', '--format=%P', said['sha']).split()
        self.assertEqual(parents, [head, moved_base])  # a merge commit of the base, never a rebase (FP1)
        self.assertEqual(git(self.forge.bare, 'log', '-1', '--format=%s', said['sha']), 'Merge origin/mod/base into units/x')

    def test_a_conflict_is_said_and_undone_and_a_moved_branch_is_refused(self):
        head = self.forge.commit('units/x', {'a.txt': 'branch\n'})
        self.forge.commit('mod/base', {'a.txt': 'base\n'})
        outcome, said = self.merger.merge(self.asked(head))
        self.assertEqual((outcome, said['paths'], self.forge.tip('units/x')), ('conflict', ['a.txt'], head))
        self.assertEqual(self.merger.merge(self.asked('f' * 40))[0], 'moved')

    def test_a_union_file_both_sides_touched_merges_as_a_checkout_merges_it(self):
        # MERGE-UNION: the clone has no work tree, so merge-tree read no .gitattributes: the board (merge=union) touched by
        # two PRs conflicted at the service (#692 behind #691, 13/11 21:30 UTC) where git merge in a checkout merges it
        self.forge.commit('mod/base', {'.gitattributes': 'board.md merge=union\n', 'board.md': 'one\ntwo\nthree\n'})
        head = self.forge.commit('units/x', {'board.md': 'one\ntwo\nbranch row\nthree\n'})
        self.forge.commit('mod/base', {'board.md': 'one\ntwo, edited\nthree\n'})
        outcome, said = self.merger.merge(self.asked(head))
        self.assertEqual(outcome, 'merged', said)
        merged = git(self.forge.bare, 'show', f"{said['sha']}:board.md").splitlines()
        self.assertIn('branch row', merged)
        self.assertIn('two, edited', merged)

    def test_the_clone_is_blobless_and_made_ahead_and_the_merge_writes_no_work_tree(self):
        # BRANCH-MERGE-FAST (criterion 3): #672's delivery waited 71.2 s for the service's merge, a whole clone (186 MB) on
        # its 0.25 vCPU; the clone is now of the commits and trees (14 MB), made at the look's start, and merge-tree merges
        # with no work tree, so only the blobs both sides changed are fetched
        git(self.forge.bare, 'config', 'uploadpack.allowFilter', 'true')
        self.merger.warm()
        clone = self.box.checkout_of({'repo': REPO})
        self.assertEqual(git(clone, 'config', 'remote.origin.partialclonefilter'), 'blob:none')
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        self.forge.commit('mod/base', {'c.txt': 'c\n'})
        outcome, said = self.merger.merge(self.asked(head))
        self.assertEqual((outcome, self.forge.tip('units/x')), ('merged', said['sha']))
        self.assertEqual(sorted(path.name for path in clone.iterdir()), ['.git'])  # no work tree written
        self.assertEqual(git(self.forge.bare, 'show', f"{said['sha']}:c.txt"), 'c')  # the base's change in the merge

    def test_a_premerge_of_a_branch_behind_its_base_is_the_commit_the_delivery_merges(self):
        # PREMERGE (the Torre, 13/11): the base moved under units/x; the Merger merges it into the head on a ref of its own,
        # the branch untouched, and the delivery's merge, a second later, is that very commit: the pre-gate ran its plan and
        # its checks on it, so the gate finds them in the cache
        import time
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        moved = self.forge.commit('mod/base', {'c.txt': 'c\n'})
        outcome, said = self.merger.premerge(dict(self.asked(head), premerge=True))
        self.assertEqual((outcome, said['onto'], said['ref'], said['head']), ('premerged', moved, f'premerge/units/x/{moved[:12]}', head))
        self.assertEqual(self.forge.tip(said['ref']), said['sha'])
        self.assertEqual(self.forge.tip('units/x'), head)  # the PR's branch is not touched
        time.sleep(1.1)  # another second: the merge's own dates are the base's, not the clock's
        outcome, merged = self.merger.merge(self.asked(head))
        self.assertEqual((outcome, merged['sha'], self.forge.tip('units/x')), ('merged', said['sha'], said['sha']))
        again = self.forge.commit('mod/base', {'d.txt': 'd\n'})  # the base moves again: a new ref, the old one deleted
        _, said2 = self.merger.premerge(dict(self.asked(said['sha']), premerge=True))
        self.assertEqual(said2['ref'], f'premerge/units/x/{again[:12]}')
        refs = git(self.forge.bare, 'for-each-ref', '--format=%(refname)', 'refs/heads/premerge')
        self.assertEqual(refs.split(), [f'refs/heads/{said2["ref"]}'])

    def test_the_delivery_pushes_the_premerges_commit_without_merging_again_and_says_its_steps(self):
        # MERGE-REUSE (criterion 3): #690 and #692 waited 19.4 and 20.5 s for the delivery's merge, the same commit a
        # premerge had made minutes before; it is pushed as it is, and each step's seconds are said
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        self.forge.commit('mod/base', {'c.txt': 'c\n'})
        _, said = self.merger.premerge(dict(self.asked(head), premerge=True))

        def refused(*args):
            raise AssertionError('merged again')
        self.merger.combine = refused
        outcome, merged = self.merger.merge(self.asked(head))
        self.assertEqual((outcome, merged['sha'], merged['reused'], self.forge.tip('units/x')),
                         ('merged', said['sha'], True, said['sha']))
        self.assertEqual(sorted(k for k in merged if k.endswith('_s')), ['combine_s', 'fetch_s', 'push_s'])
        git(self.forge.work, 'fetch', '-q', 'origin')  # the merge the Merger pushed
        head2 = self.forge.commit('units/x', {'e.txt': 'e\n'})  # a head no premerge made: merged as before
        self.forge.commit('mod/base', {'f.txt': 'f\n'})
        del self.merger.combine
        outcome, merged = self.merger.merge(self.asked(head2))
        self.assertEqual((outcome, merged['reused']), ('merged', False))

    def test_a_premerge_of_a_head_the_base_holds_or_holds_the_base_is_no_merge(self):
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        self.assertEqual(self.merger.premerge(dict(self.asked(head), premerge=True))[0], 'current')
        git(self.forge.work, 'checkout', '-q', 'mod/base')
        git(self.forge.work, 'merge', '-q', '--no-edit', 'origin/units/x')
        git(self.forge.work, 'push', '-q', 'origin', 'HEAD:refs/heads/mod/base')
        self.assertEqual(self.merger.premerge(dict(self.asked(head), premerge=True))[0], 'landed')

    def test_its_look_takes_each_once_and_says_the_outcome(self):
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})

        class Db:
            def __init__(self, asked):
                self.asked, self.said = [asked], {}

            def rows(self, sql, params=None):
                if sql == branches.OPEN:
                    return [(json.dumps(a),) for a in self.asked if (a['id'], 'taken') not in self.said]
                payload = json.loads(params['payload'])
                if (payload['id'], payload['state']) in self.said:
                    return []
                self.said[(payload['id'], payload['state'])] = payload
                return [(None,)]
        db = Db(self.asked(head))
        self.assertEqual(self.merger.step(db), 1)
        self.assertEqual(db.said[('1', 'current')]['sha'], head)
        self.assertEqual(self.merger.step(db), 0)

    def test_the_routes_are_the_ports(self):
        verbs = {(verb, pattern) for verb, pattern, _ in http_port.ROUTES}
        self.assertIn(('POST', r'/v1/branch-merge'), verbs)
        self.assertIn(('GET', r'/v1/branch-merge/(?P<ident>[0-9]{1,24})'), verbs)


class TheDeliveryFollows(unittest.TestCase):
    class Port:
        def __init__(self, said, refuse=None):
            self.said, self.refuse, self.calls = said, refuse, []

        def call(self, method, path, body=None):
            self.calls.append((method, path, body))
            if self.refuse:
                import gate_infra
                raise gate_infra.Refused(self.refuse, 'no')
            return {'id': '5', 'state': 'asked'} if method == 'POST' else self.said

    def test_the_delivery_follows_the_services_merge_and_merges_itself_without_the_route(self):
        ran, said = [], []

        def run(args, **_):
            ran.append(args)
            return subprocess.CompletedProcess(args, 0, '', '')
        port = self.Port({'state': 'merged', 'sha': 'm' * 40, 'merge_s': 1.2})
        got = deliver._merged_by_service(port, Path('/tree'), 'units/x', 'h' * 40, 'origin', 'mod/base', run, said.append)
        self.assertEqual(got, ('m' * 40, 0))
        self.assertEqual(port.calls[0], ('POST', '/v1/branch-merge', {'branch': 'units/x', 'head': 'h' * 40, 'base': 'mod/base'}))
        self.assertEqual([args[:3] for args in ran], [['git', 'fetch', '--quiet'], ['git', 'merge', '--quiet']])
        self.assertNotIn('push', ' '.join(' '.join(args) for args in ran))  # the lane pushes nothing
        for state, want in (({'state': 'current'}, ('h' * 40, 0)), ({'state': 'conflict', 'paths': ['a']}, ('h' * 40, 1)),
                            ({'state': 'moved', 'tip': 't'}, ('h' * 40, 1)), ({'state': 'failed', 'why': 'x'}, None)):
            self.assertEqual(deliver._merged_by_service(self.Port(state), Path('/tree'), 'units/x', 'h' * 40, 'origin',
                                                        'mod/base', run, said.append), want, state)
        self.assertIsNone(deliver._merged_by_service(self.Port({}, refuse=404), Path('/tree'), 'units/x', 'h' * 40,
                                                     'origin', 'mod/base', run, said.append))


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)

    def test_a_merge_asked_at_the_port_is_answered_and_a_bad_ask_refused(self):
        said = self.world.port('POST', '/v1/branch-merge', 'torre', {'branch': 'units/x', 'head': 'a' * 40, 'base': 'mod/base'})
        self.assertEqual(self.world.port('GET', f"/v1/branch-merge/{said['id']}", 'torre')['state'], 'asked')
        for body in ({'branch': 'main', 'head': 'a' * 40, 'base': 'b'}, {'branch': 'units/../x', 'head': 'a' * 40, 'base': 'b'},
                     {'branch': 'units/x', 'head': 'short', 'base': 'b'}, {'branch': 'units/x', 'head': 'a' * 40, 'base': '-x y'}):
            with self.assertRaises(Exception) as refused:
                branches.ask(self.world.db, ('installation', None), body)
            self.assertEqual(getattr(refused.exception, 'status', None), 400, body)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class PremergeOnPostgres(unittest.TestCase):
    """PREMERGE end to end on the log (the Torre, 13/11): the base pushed under a unit branch, the pre-gate asks, the
    Merger premerges on a ref of its own, the pre-gate plans that merge, and the delivery's merge is that very commit."""

    asked = TheMerger.asked

    def setUp(self):
        TheMerger.setUp(self)  # the forge and the Merger of the other tests, not their tests
        from infra_db import psql
        import test_db
        name, self.db = psql.migrated(URL)
        self.addCleanup(test_db.destroy, URL, name)

    def pushed(self, ident, ref, after):
        owner, name = REPO.split('/')
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "(%(id)s, null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                     {'id': ident, 'payload': json.dumps({'delivery': {'event': {'payload': {
                         'repository': {'owner': {'slug': owner}, 'name': name}, 'refUpdates': [{'ref': ref, 'after': after}]}}}})})

    def test_a_base_that_moves_under_a_branch_has_its_combination_planned_and_the_delivery_merges_that_commit(self):
        from tower_infra import pregate
        made = []
        look = pregate.Pregate(base_branch='mod/base', tenant='t',
                               create=lambda db, who, body: made.append(body) or {'id': f'j{len(made)}'})
        look.who = lambda db: ('tenant', 't')
        head = self.forge.commit('units/x', {'b.txt': 'b\n'})
        self.pushed('p1', 'refs/heads/units/x', head)
        look.follow(self.db)  # the branch's own push (no base pushed yet in the log: nothing to plan against)
        moved = self.forge.commit('mod/base', {'c.txt': 'c\n'})
        self.pushed('p2', 'refs/heads/mod/base', moved)
        look.follow(self.db)  # the base moved: units/x's head asked to be premerged
        self.assertEqual(self.merger.step(self.db), 1)  # the Merger's look, by the same event as a delivery's merge
        self.assertEqual(look.premerged(self.db), 1)
        spec = json.loads(__import__('base64').b64decode(made[-1]['input_uri'].split(',', 1)[1]))
        self.assertEqual((spec['ref'], spec['base']), (f'refs/heads/premerge/units/x/{moved[:12]}', moved))
        self.assertEqual(self.forge.tip(spec['ref'][len('refs/heads/'):]), spec['commit'])
        outcome, merged = self.merger.merge(self.asked(head))  # the delivery, later
        self.assertEqual((outcome, merged['sha']), ('merged', spec['commit']))  # the commit the pre-gate planned
        self.assertEqual(made[-1]['input_digest'], pregate.digest('gate-plan', merged['sha'], moved))  # its plan: cached


if __name__ == '__main__':
    unittest.main()
