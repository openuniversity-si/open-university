# RETRO-API plan

Receive and keep. No analysis, no aggregation, no prose, no check on the merge path.

## Commits (dependency graph)

| # | Commit | Files it owns | Depends on |
|---|---|---|---|
| 1 | audit.md and plan.md | `docs/units/RETRO-API/audit.md`, `plan.md` | none |
| 2 | The store: header + byte-for-byte body, sha256, 50 MB ceiling with a pointer above it, secret scan through gitleaks; unit manifest, covers, test script, `retro/` gitignored | `scripts/lib/retro.py`, `scripts/tests/test_retro.py`, `scripts/tests/retro.test.sh`, `scripts/tests/covers/retro.json`, `units/engine-retro/unit.json`, `.gitignore` | 1 (real: the size decision) |
| 3 | The index: `retro/index.jsonl`, idempotence by digest | `scripts/lib/retro.py`, `scripts/tests/test_retro.py` | 2 (real) |
| 4 | The ingest: `scripts/retro ingest --unit <id> [--session <sid>]` | `scripts/retro`, `scripts/lib/retro.py`, `scripts/tests/test_retro.py` | 3 (real) |
| 5 | The door: `scripts/retro receive --unit <id> --session <sid> [--path <file>]`, shape check | `scripts/lib/retro.py`, `scripts/tests/test_retro.py` | 3 (real), 4 (file collision on `scripts/retro`) |
| 6 | Future consumers and the proof on real data | `docs/units/RETRO-API/audit.md` | 4, 5 (real) |
| 7 | retro.md | `docs/units/RETRO-API/retro.md` | the gate |

Critical path: 1 (5 min) → 2 (10) → 3 (5) → 4 (10) → 5 (5) → 6 (10) → gate (≈ 5) → 7 (10): about 60 minutes.
No fan-out: commits 2 to 5 all edit one small module (`scripts/lib/retro.py`, under 300 lines), so every edge
between them is real or a collision on that one file. Splitting it into four files to run four writers would cost more
than the minutes it saves. Decision: sequential, one writer.

## Cheapest useful effort
Action: the one full `scripts/gate-dev --pr 798` run on the final head
Cost: about 5 to 10 min of session time, no money
Requirement: A Torre's merge train, on Daniel's order, needs a gated head to merge this unit (the verdict of record)
Cheaper rejected: targeted `bash scripts/tests/retro.test.sh` only (it proves the module, not the stages the diff touches, such as units, covers, generated files and CODEOWNERS, so it cannot give A Torre a mergeable head); several gate runs while working (the brief allows one, and the pre-push hook already runs the selected script tests on every push)

## Premises

| Premise | Blast radius | Critical |
|---|---|---|
| A transcript is JSONL with a `type` on every line (audit A3) | the door's shape check | no |
| One log is far under 50 MB (audit A4) | bytes vs pointer | no |
| The store is not committed here (audit, store decision) | where the logs live; reversible, a directory moves as is | no |
| gitleaks is installed by `scripts/cloud/setup.sh` (A6) | the scan; without it every file is refused (fail closed) | no |
| Other units' transcripts are not reachable from this container (A7, A8) | the proof on three units uses what is reachable and says so | no |

## Tests

- Per commit: `python3 -m pytest scripts/tests -k "retro" -q` (the file also runs as `python3 scripts/tests/test_retro.py`).
- Once at the end: `bash scripts/gate-dev --pr 798`. Per commit, in fact: `bash scripts/tests/retro.test.sh` (A12).

## Known base defects

The config change store is rate-limited by GitHub at launch (audit A9); setup runs with `OU_CONFIG_STORE=file`.

## Plan changes during execution

- Item 2 gained a second commit: the first real ingest showed every Claude Code transcript trips gitleaks'
  `generic-api-key` on its `turnAttributionKey` UUID (audit A11). The retro-only exception `retro.scan_allowlist` was
  added before the proof.
- Item 5 gained a one-line commit: a refusal printed its source twice.
- The targeted test command is `bash scripts/tests/retro.test.sh`, because pytest is not installed here (audit A12).
- The gate runs after the session's GitHub write-budget block clears (audit A9), because `gate-dev --pr` reads the PR
  through that client.
