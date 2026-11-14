# WR1 plan

Premises: P-41 (high: no literal tunables; a wrong premise sends values back into code). No CRITICAL premise: no money, production or source-of-truth change.

## Commits (dependency graph)
1. audit (this file's sibling): `docs/units/WR1/audit.md`.
2. plan: `docs/units/WR1/plan.md`.
3. Registry + helper: `config/registry/gate.json` (`gate.worktree_*` entries), `scripts/lib/gate-isolation.sh` (`ou_worktree_id`, `ou_worktree_dir`, `ou_worktree_port`), `scripts/tests/gate-isolation.test.sh`. Depends on nothing.
4. Wire + remove locks: `scripts/gate-local`, `scripts/lib/gate-fixed.sh`, `scripts/lib/gate_suite.py`, `scripts/tests/test_root_identity.py`. Depends on 3.
5. Concurrency proof + docs: `scripts/tests/gate-worktree-resources.test.sh`, `scripts/lib/gate-script-tests.json`, `AGENTS.md`, `docs/operations/local-gate.md`, postmortem reference. Depends on 4.
6. retro.

All sequential: each commit's files overlap the next one's tests. Gate files change citing D-025 and D-069.

## Tests
Per commit: `bash scripts/tests/gate-isolation.test.sh`, `python3 -m unittest scripts.tests.test_root_identity`, the new concurrency test. One final `gate-dev`.

## Known base defects
tower-catalog cover concurrency and read-latency timing tests on 4 vCPU (never changed).
