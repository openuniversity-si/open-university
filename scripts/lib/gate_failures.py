"""The failing tests a gate run saw, with a signature, for the verdict (GS1, D-069 items 6 and 9).

gate.failed carries `failing_tests` [{id, stage, signature}] and gate.passed/gate.failed carry `cached_tests`
[{id, key, source}], so a failure is classified and compared with the base's without a session: the same test with the
same signature on a PR and on the base is a pre-existing defect, a new signature is the PR's.

  script   a FAIL entry of script-tests.json (gate_test_cache), signature from the tail of its output

The script tests are the only per-test stage the gate runs: any other failed stage (a scan, the structure check,
shellcheck) lists no test, and its log is the evidence. The vitest and Playwright readers left with Open University's
stages (F46, D-113).

A signature is the last error line with colour codes, absolute paths, digits and runs of space removed, capped at
gate.failing_signature_chars. At most gate.failing_tests_max tests are listed, by id; the total is kept.
"""
import json
import re
from pathlib import Path

import config

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
PATH = re.compile(r'(?<![\w.@+-])(?:/[\w.@+-]+){2,}/([\w.@+-]+)')
ERROR = re.compile(r'^\s*(?:[A-Za-z_.]*(?:Error|Exception)\b|FAIL\b|FAILED\b|not ok\b|Traceback)')


def normalize(text):
    """One comparable line: no colour codes, absolute paths reduced to the file name, digits to N, spaces collapsed."""
    text = ANSI.sub('', text or '')
    line = next((line.strip() for line in text.splitlines() if line.strip()), '')
    line = PATH.sub(r'\1', line)
    line = re.sub(r'(?<![A-Za-z_])\d+(?:\.\d+)?(?![A-Za-z_])', 'N', line)
    line = re.sub(r'\s+', ' ', line)
    return line[:config.get('gate.failing_signature_chars')]


def last_error(lines):
    """The last error-looking line (a unittest report ends with the assertion); the last non-empty line otherwise."""
    lines = [ANSI.sub('', line) for line in lines]
    return next((line for line in reversed(lines) if ERROR.match(line) and not line.startswith(('FAILED', 'Traceback'))),
                next((line for line in reversed(lines) if line.strip()), ''))


def script_failures(records):
    return [{'id': item['test'], 'stage': 'script tests', 'signature': normalize(last_error(item.get('tail') or []))}
            for item in records if item['result'] == 'FAIL']


def _records(logs):
    path = Path(logs) / 'script-tests.json'
    if not path.is_file():
        return []
    try:
        records = json.loads(path.read_text())
        return records if isinstance(records, list) else []
    except ValueError:
        return []


def cached_tests(logs):
    """The script tests the cache reported as PASS: id, the key that matched and the run that recorded it."""
    return [{'id': item['test'], 'key': item['key'], 'source': item['source']}
            for item in _records(logs) if item.get('cached') and item.get('key') and item.get('source')]


def failing(logs):
    """(the failing tests, capped, and their total): the FAIL entries of the run's script-tests.json, by id. A failed
    stage that is not `script tests` adds none (its log has no per-test shape the gate reads), whatever its log says."""
    unique = {item['id']: item for item in script_failures(_records(logs))}
    ordered = sorted(unique.values(), key=lambda item: item['id'])
    return ordered[:config.get('gate.failing_tests_max')], len(ordered)
