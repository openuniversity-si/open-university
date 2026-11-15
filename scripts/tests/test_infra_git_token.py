"""GIT-TOKEN-AUTH (criterion 3): the delivery's merge fetched in 8.6 to 9.5 s and pushed in 8.2 to 9.4 s (#695, #696, 13/11),
each request git authenticated running the credential helper's two `origin` processes on the service's quarter of a vCPU.
A container made with token_auth mints the forge's token once and gives it to git as its Basic header, in the environment;
the helper stays behind it. Hermetic: a fake run."""
import base64
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import container  # noqa: E402

TOKEN = 'h.' + base64.urlsafe_b64encode(b'{"exp": 4102444800}').decode().rstrip('=') + '.s'  # a JWT's shape, exp 2100
URL = 'https://origin.cursor.com'


class Run:
    def __init__(self, git=None, mint=(0, TOKEN + '\n')):
        self.calls, self.git, self.mint = [], list(git or []), mint

    def __call__(self, args, **options):
        self.calls.append((list(args), dict(options.get('env') or {})))
        if args[:3] == ['origin', 'auth', 'token']:
            code, out = self.mint
            return subprocess.CompletedProcess(args, code, out, '')
        code, err = self.git.pop(0) if self.git else (0, '')
        return subprocess.CompletedProcess(args, code, 'ok', err)

    def gits(self):
        return [(args, env) for args, env in self.calls if args[0] == 'git']

    def mints(self):
        return [args for args, _ in self.calls if args[:3] == ['origin', 'auth', 'token']]


def box(run, token_auth=True):
    return container.Container('/tmp/x', credential=lambda: 'crsr_key', forge_url=URL, cli='origin', run=run,
                               environ={}, token_auth=token_auth)


def header(env):
    count = int(env.get('GIT_CONFIG_COUNT') or 0)
    found = {env.get(f'GIT_CONFIG_KEY_{n}'): env.get(f'GIT_CONFIG_VALUE_{n}') for n in range(count)}
    return found.get(f'http.{URL}/.extraHeader')


class TheToken(unittest.TestCase):
    def test_git_gets_the_minted_token_as_the_forges_basic_header_in_its_environment_never_its_argv(self):
        run = Run()
        made = box(run)
        made.git('fetch', 'origin')
        made.git('push', 'origin', 'x')
        self.assertEqual(len(run.mints()), 1)  # minted once, kept
        for args, env in run.gits():
            basic = base64.b64encode(f'x-access-token:{TOKEN}'.encode()).decode()
            self.assertEqual(header(env), f'Authorization: Basic {basic}')
            self.assertFalse([each for each in args if TOKEN in each or basic in each])  # never on the command line
            self.assertIn('credential.helper=' + container.helper('origin'), args)  # the helper stays behind it

    def test_a_refused_token_is_forgotten_and_the_helper_answers_the_same_call_without_minting_again(self):
        run = Run(git=[(128, 'fatal: Authentication failed for https://origin.cursor.com/x.git'), (0, ''), (0, '')])
        made = box(run)
        made.git('fetch', 'origin')
        self.assertEqual([header(env) is not None for _, env in run.gits()], [True, False])
        made.git('fetch', 'origin')  # within TOKEN_RETRY_S: no new token, the helper again
        self.assertEqual((len(run.mints()), header(run.gits()[-1][1])), (1, None))

    def test_a_failed_mint_leaves_the_helper_and_waits_before_trying_again(self):
        run = Run(mint=(1, ''))
        made = box(run)
        made.git('fetch', 'origin')
        made.git('fetch', 'origin')
        self.assertEqual(len(run.mints()), 1)
        self.assertEqual([header(env) for _, env in run.gits()], [None, None])

    def test_another_failure_is_the_calls_own_and_keeps_the_token(self):
        run = Run(git=[(1, 'fatal: couldn\'t find remote ref x')])
        with self.assertRaises(container.Unprepared):
            box(run).git('fetch', 'origin', 'x')
        self.assertEqual(len(run.gits()), 1)

    def test_without_token_auth_git_runs_as_before(self):
        run = Run()
        box(run, token_auth=False).git('fetch', 'origin')
        self.assertEqual((run.mints(), header(run.gits()[0][1])), ([], None))

    def test_the_live_services_containers_ask_for_it(self):
        main = (ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        self.assertEqual(main.count('token_auth=True'), 2)  # the runner's slots, the pushed heads (the Merger's clone: dormant, D-316)


if __name__ == '__main__':
    unittest.main()
