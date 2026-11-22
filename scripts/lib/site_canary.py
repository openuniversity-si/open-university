"""Read-only synthetic HTTP canary for the live site (M6, D-346, D-359 proposed).

Probes the public Open University site without AWS credentials, secrets, or any write:
  1. GET /api/health  HTTP 200, Cache-Control: no-store, JSON status "ok", non-empty catalog sha/source and release.
  2. GET /            HTTP 200, HTML body, and the security baseline headers apps/web declares
                      (Strict-Transport-Security, X-Content-Type-Options, Referrer-Policy, X-Frame-Options,
                      Content-Security-Policy).

Target is 100% pass (D-337): any failed probe or missing security header exits 1.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

DEFAULT_TIMEOUT_S = float(len('0123456789'))
USER_AGENT = 'tower-site-canary/1'
HEALTH_PATH = '/api/health'
HOME_PATH = '/'
REQUIRED_EXACT_HEADERS = (
    ('x-content-type-options', 'nosniff'),
    ('x-frame-options', 'deny'),
    ('referrer-policy', 'strict-origin-when-cross-origin'),
)


def validate_url(url):
    """Return (clean_base_url, finding_or_none). Only http/https URLs with a host and no credentials are allowed."""
    raw = (url or '').strip()
    if not raw:
        return '', 'missing site URL (pass --url or set TOWER_SITE_URL)'
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ('http', 'https'):
        return '', f'unsupported URL scheme {parsed.scheme!r}; expected http or https'
    if not parsed.netloc or parsed.username or parsed.password or any(ch.isspace() for ch in raw):
        return '', f'invalid site URL {raw!r}'
    base = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))
    return base, None


def _header_map(headers):
    if headers is None:
        return {}
    if isinstance(headers, dict):
        return {str(key).lower(): str(value).strip() for key, value in headers.items()}
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def fetch(url, timeout=DEFAULT_TIMEOUT_S, opener=urllib.request.urlopen):
    """Perform one read-only GET and return {url, status, headers, body, elapsed_s, transport_error}."""
    request = urllib.request.Request(url, method='GET', headers={'User-Agent': USER_AGENT})
    started = time.monotonic()
    try:
        with opener(request, timeout=timeout) as response:
            raw_status = getattr(response, 'status', None)
            status = int(raw_status if raw_status is not None else response.getcode())
            headers = _header_map(response.headers)
            raw = response.read()
            body = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw)
            return {
                'url': url,
                'status': status,
                'headers': headers,
                'body': body,
                'elapsed_s': time.monotonic() - started,
                'transport_error': None,
            }
    except urllib.error.HTTPError as error:
        raw = error.read() if hasattr(error, 'read') else b''
        body = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw)
        return {
            'url': url,
            'status': int(error.code),
            'headers': _header_map(error.headers),
            'body': body,
            'elapsed_s': time.monotonic() - started,
            'transport_error': None,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            'url': url,
            'status': None,
            'headers': {},
            'body': '',
            'elapsed_s': time.monotonic() - started,
            'transport_error': f'{type(error).__name__}: {error}',
        }


def probe_health(base_url, timeout=DEFAULT_TIMEOUT_S, opener=urllib.request.urlopen):
    """Probe GET /api/health for HTTP 200, no-store cache header, status ok, and catalog metadata."""
    response = fetch(base_url + HEALTH_PATH, timeout=timeout, opener=opener)
    findings = []
    if response['transport_error']:
        findings.append(f'GET {HEALTH_PATH}: transport failure ({response["transport_error"]})')
    elif response['status'] != HTTPStatus.OK:
        findings.append(f'GET {HEALTH_PATH}: expected HTTP {int(HTTPStatus.OK)}, got {response["status"]}')
    else:
        cache_control = response['headers'].get('cache-control', '').lower()
        if 'no-store' not in cache_control:
            findings.append(f'GET {HEALTH_PATH}: Cache-Control missing no-store ({cache_control!r})')
        try:
            payload = json.loads(response['body'])
        except ValueError as error:
            findings.append(f'GET {HEALTH_PATH}: body is not valid JSON ({error})')
            payload = None
        if payload is not None:
            if not isinstance(payload, dict):
                findings.append(f'GET {HEALTH_PATH}: JSON payload is not an object')
            else:
                if payload.get('status') != 'ok':
                    findings.append(f'GET {HEALTH_PATH}: status is {payload.get("status")!r}, expected "ok"')
                catalog = payload.get('catalog')
                if not isinstance(catalog, dict):
                    findings.append(f'GET {HEALTH_PATH}: missing catalog object')
                else:
                    release = catalog.get('release')
                    if isinstance(release, bool) or not isinstance(release, int):
                        findings.append(f'GET {HEALTH_PATH}: catalog.release must be an integer, got {release!r}')
                    if not isinstance(catalog.get('sha'), str) or not catalog['sha'].strip():
                        findings.append(f'GET {HEALTH_PATH}: catalog.sha is missing or empty')
                    if not isinstance(catalog.get('source'), str) or not catalog['source'].strip():
                        findings.append(f'GET {HEALTH_PATH}: catalog.source is missing or empty')
    return {
        'name': 'health',
        'path': HEALTH_PATH,
        'ok': not findings,
        'status': response['status'],
        'elapsed_s': response['elapsed_s'],
        'findings': findings,
    }


def probe_home(base_url, timeout=DEFAULT_TIMEOUT_S, opener=urllib.request.urlopen):
    """Probe GET / for HTTP 200, non-empty HTML, and apps/web baseline security headers."""
    response = fetch(base_url + HOME_PATH, timeout=timeout, opener=opener)
    findings = []
    if response['transport_error']:
        findings.append(f'GET {HOME_PATH}: transport failure ({response["transport_error"]})')
    elif response['status'] != HTTPStatus.OK:
        findings.append(f'GET {HOME_PATH}: expected HTTP {int(HTTPStatus.OK)}, got {response["status"]}')
    else:
        headers = response['headers']
        content_type = headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            findings.append(f'GET {HOME_PATH}: expected text/html content-type, got {content_type!r}')
        if not response['body'].strip():
            findings.append(f'GET {HOME_PATH}: response body is empty')
        for header, expected in REQUIRED_EXACT_HEADERS:
            actual = headers.get(header, '').lower()
            if actual != expected:
                findings.append(f'GET {HOME_PATH}: header {header} is {actual!r}, expected {expected!r}')
        hsts = headers.get('strict-transport-security', '').lower()
        if 'max-age=' not in hsts or 'includesubdomains' not in hsts:
            findings.append(f'GET {HOME_PATH}: Strict-Transport-Security missing max-age/includeSubDomains ({hsts!r})')
        csp = headers.get('content-security-policy') or headers.get('content-security-policy-report-only') or ''
        if not csp.strip():
            findings.append(f'GET {HOME_PATH}: missing Content-Security-Policy header')
    return {
        'name': 'home',
        'path': HOME_PATH,
        'ok': not findings,
        'status': response['status'],
        'elapsed_s': response['elapsed_s'],
        'findings': findings,
    }


def run_canary(url, timeout=DEFAULT_TIMEOUT_S, opener=urllib.request.urlopen):
    """Run all read-only live-site probes; ok is True only when 100% of probes pass (D-337)."""
    base, url_finding = validate_url(url)
    if url_finding:
        return {'ok': False, 'url': url or '', 'probes': [], 'findings': [url_finding]}
    probes = [
        probe_health(base, timeout=timeout, opener=opener),
        probe_home(base, timeout=timeout, opener=opener),
    ]
    findings = [item for probe in probes for item in probe['findings']]
    return {'ok': not findings, 'url': base, 'probes': probes, 'findings': findings}


def format_summary(verdict):
    """Human-readable summary lines for logs and GitHub issue bodies."""
    if verdict['ok']:
        parts = ', '.join(f'{probe["name"]}={probe["status"]} ({probe["elapsed_s"]:.3f} s)' for probe in verdict['probes'])
        return f'site-canary ok: {verdict["url"]} ({parts})'
    lines = [f'site-canary RED: {verdict["url"]} ({len(verdict["findings"])} finding(s))']
    lines += [f'  - {finding}' for finding in verdict['findings']]
    return '\n'.join(lines)


def main(argv=None, environ=None, opener=urllib.request.urlopen):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog='scripts/site-canary', description=__doc__.splitlines()[0])
    parser.add_argument('--url', default=environ.get('TOWER_SITE_URL', ''), help='live site base URL (or TOWER_SITE_URL)')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT_S, help='per-request timeout in seconds')
    parser.add_argument('--json', action='store_true', dest='as_json', help='emit the verdict as JSON')
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        print('site-canary RED: --timeout must be positive', file=sys.stderr)
        return 1
    verdict = run_canary(args.url, timeout=args.timeout, opener=opener)
    if args.as_json:
        print(json.dumps(verdict, indent=1, sort_keys=True))
    else:
        print(format_summary(verdict))
    return 0 if verdict['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
