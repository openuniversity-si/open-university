# Postmortem YYYY-MM-DD: <what went wrong, in one line>

Blameless (D-069 item 9). The question is which check was missing, not who acted. File name:
`YYYY-MM-DD-<slug>.md`. `scripts/lib/postmortem_check.py` (the `structure check` stage) refuses this file until the
preventing check below exists and its test exists.

## What happened

## Impact

## Why (five whys)

1. Why did it happen?

## The class fix

What the gate now checks, and why that check covers the class and not only the instance.

## Preventing check

- check: <gate check file, e.g. scripts/lib/config_check.py>
- test: <test file>::<test function name, e.g. scripts/tests/test_config_check.py::test_an_inline_fallback_fails>
