# WR1 audit: shared host locks in the gate (enforcement audit 26/10, rule 12b, fix R9)

Read-only findings, evidence from `origin/mod/roadmap-integration` (a2c09043).

## Shared host resources
| Resource | Where | Effect |
|---|---|---|
| `/tmp/tower-e2e.lock` | `scripts/gate-local` (browser inventory, e2e stage), `scripts/lib/gate-fixed.sh` (capture regression), `scripts/lib/gate_suite.py` (playwright `--list`), `scripts/lib/ship_verify.py` (production capture) | two gates on one host run their browser stages one after the other |
| `/tmp/tower-perf.lock` | `scripts/gate-local` (performance tests) | same, for the perf stage |
| `gate.slot_dir=/tmp` | `config/registry/gate.json`, `scripts/lib/gate-isolation.sh` | the slot semaphore (3 slots) is the CPU guard; it stays |
| `TOWER_E2E_PORT` | `ou_free_port` picks any free port at start | no collision, but not stable per worktree and racy between probe and bind |
| `TMPDIR` | not set by the gate | tests write to the shared system temp dir |

## Already isolated per checkout
Test database (`ou_test_db_name`, hash of the path, D-064 (b)); `.next`, `test-results` and `.gate/` live inside the checkout; `--pr` checkouts use a fixed per-slot path that one slot holder owns.

## What the locks protect
The e2e server port and the shared temp dir. With a port derived from the checkout and a temp/run directory derived from the checkout, nothing else is shared: the capture-regression tests bind port 0, and the Playwright `--list` starts no server.

## Out of scope
`ship_verify.py` captures production through the frozen release tail (D-054); its lock is left to the release pipeline of roadmap step 8.

## Existing mechanisms reused
`ou_test_db_name` hashing style, `ou_free_port`, `ou_config_value`, the `gate.json` registry, `scripts/tests/gate-isolation.test.sh`, `scripts/tests/test_root_identity.py`.
