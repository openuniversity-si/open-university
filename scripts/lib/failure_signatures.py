"""The failure signature of a script test (GS1, D-069 items 6 and 9; D-322): the one gate.failed and base.red carry.

A signature is the last error line with colour codes, absolute paths, digits and runs of space removed, capped at
gate.failing_signature_chars. A layer-0 module (engine-events, beside the verdict contracts): the known-defect detector
and its adapters compare signatures without importing the gate; gate_failures re-exports every name here.

  normalize(text)          one comparable line
  last_error(lines)        the last error-looking line of an output tail
  script_failures(records) [{id, stage, signature}] of the FAIL entries
  records(logs)            the entries of a run's script-tests.json
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


def records(logs):
    """The entries of a run's script-tests.json (gate_test_cache), [] when it is absent or unreadable."""
    path = Path(logs) / 'script-tests.json'
    if not path.is_file():
        return []
    try:
        found = json.loads(path.read_text())
        return found if isinstance(found, list) else []
    except ValueError:
        return []
