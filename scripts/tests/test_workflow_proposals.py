"""Workflow proposals and live-site canary (PR W, D-087, D-359 proposed). Hermetic: no network calls.

Verifies: REQ-github-truth
"""
import contextlib
import io
import json
import sys
import unittest
import urllib.error
import urllib.parse
from http import HTTPStatus
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import site_canary

SITE_URL = urllib.parse.urlunsplit(('https', 'site.test', '', '', ''))
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


if __name__ == '__main__':
    unittest.main()
