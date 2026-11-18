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
import config
# D-322: the signature is layer 0 (failure_signatures, engine-events); the gate's callers keep these names.
from failure_signatures import ANSI, ERROR, PATH, last_error, normalize, records as _records, script_failures  # noqa: F401


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
