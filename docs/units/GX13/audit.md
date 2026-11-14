# GX-13 audit (read-only findings)

Base `mod/roadmap-integration` eaeeb29d (contains GX-39 #705, GX-38, GX-05, GX-08). Branch `mod/gx13`, PR #729.

## Cited sources, verified on the base
- `scripts/lib/gate_adjudicate.py` (48 lines, GX-39 seam): `defect_events` (:9-29) and `adjudicate` (:32-48). Exists.
- `scripts/lib/defect_detect.py` (169 lines): `resolve_base` (:45-49), `rerun` (:72-98), `outcome` (:101-112), `adjudicate` (:115-127), `verification` (:130-145), `explained` (:148-155), `apply_to_report` (:158-169). Exists.
- `OU_GATE_BASE_SHA`: exported by `scripts/gate-local:189` (`export OU_GATE_BASE_SHA="$base"`), set from the PR's `baseRefOid` (`gate-local:174-187`, the pin's REST identity) or the batch plan's `base` (`gate-local:170-173`); empty for a plain `--sha` or a working-tree run. `gate-hooks/proof.sh` is a no-op body (GX-10 owns it). gate_report runs as a child of gate-local (`:131-134`, `:208-209`), so the variable reaches it.
- `config/registry/defects.json` (408 lines): no `never_excuse_touched` / `verify_open` key yet. `defects.transitions` (default) has no `open>resolved`.
- Tests: `scripts/tests/test_defect_detect.py` (189), `scripts/tests/test_defect_lifecycle.py` (71), `scripts/tests/defects.test.sh`; covers sidecars `scripts/tests/covers/defect-detect.json`, `defect-lifecycle.json` exist (GX-08).
- Defect records: `docs/process/defects/scripts-tests-generate-test-sh-024bbecb.yml` (KD-024bbecb) and `scripts-tests-premises-test-sh-4db6e693.yml` (KD-4db6e693), both `status: "open"`, evidence from 974cab54.

## How the base is resolved today (G-06, F-02)
`gate_adjudicate.adjudicate:39` calls `defect_detect.resolve_base()`, which runs `git rev-parse <gate.batch_base_ref>^{commit}` in the tool root (`defect_detect.py:45-49`). The result is whatever the local ref `origin/mod/roadmap-integration` points to on that machine at that moment: two sessions with different fetch states adjudicate the same PR against different bases. The recorded base (`OU_GATE_BASE_SHA`) is never read. A base sha whose objects are not local makes `git worktree add` fail and `rerun` returns `error` (the failure stays the PR's, correct but machine-dependent). Nothing fetches it.

## Which install the base re-run uses (`defect_detect.py:81-83`)
`rerun` symlinks `<tool root>/apps/web/node_modules` into the base worktree when it exists. That install is built from whatever lockfile the tool root had (with the GX-05 pin, the pinned base tip; without it, the head), not from the base's lockfile. A dependency change between the two silently changes the base result. The gate's own convention for a fresh worktree is `pnpm install --frozen-lockfile --prefer-offline` in `apps/web` (`gate-local:309-322`, `share_node_modules`), and only when the test needs the web package (`modules` flag of its covers manifest, `gate_script_tests.modules_required`).

## The excuse rule (`defect_detect.py:115-127`, `:158-169`)
A failing test in `defects.stages` is excused when its base re-run fails with the same normalized signature. Nothing looks at what the PR changed: a PR that edits a test (or what it covers) and leaves it failing with a signature the base also shows is excused (the #662 case: a failing test whose own file the PR changed). When every failing test of a failed stage is known, the stage is flipped to `result: PASS` with `raw_result: FAIL` in the report (`:166`). `gate_proof.stage_records` (`gate_proof.py:12-17`, GX-10's file) copies only `name/result/duration_ms/class` into the published verdict, so `raw_result` is dropped there; the defect id does reach the verdict through `known_defects` (`gate_proof.py:39-41`, keys `id, stage, signature, base_sha, defect`).

## Lifecycle of open defects
`verification` (`defect_detect.py:130-145`) re-runs only `resolved` defects; `open` (and `fixing`) defects are never verified, so a defect fixed on the base by an unrelated merge stays `open` forever. `defects.sync` (`defects.py:273-295`, the only writer of records from gate events) applies `defect.verified` only to `resolved` records and `defect.reopened` to `resolved/verified`. Re-run on base eaeeb29d (this audit): `bash scripts/tests/generate.test.sh` → `Ran 23 tests ... OK rc=0`; `bash scripts/tests/premises.test.sh` → `Ran 34 tests ... OK rc=0`. KD-024bbecb and KD-4db6e693 no longer reproduce and are still `open`.

## BD1 #667 (stale draft, head 28f96db5)
#667's defect-lifecycle part is a `kind` field (`load-sensitive`) on records and `defect.detected` (`defects.py` `record/sync`, `contracts/defects/defect.v1.json`, `contracts/events/defect.detected.v1.json`, test `test_a_load_sensitive_detection_is_registered...`), plus per-stage adapters (`defect_adapters.py`, `defects.stage_shapes`, vitest/eslint/browser re-runs) and `defects.max_adjudicated`. None of it addresses the recorded base, the base install, the touched-test rule or open-defect verification. The `kind` part needs contract and `defects.py` changes, and the adapters are excluded by the brief; nothing is taken. Its re-run refactor (`environment`, `run`) is kept in mind: this unit's install step lands in the same function and stays compatible with it. Credited in the PR.

## Constraints
- `gate_report.py`, `gate-local`, `gate-hooks/*` closed; `gate_proof.py` is GX-10's (running). Per-stage `raw_result` in the published verdict needs one line in `gate_proof.stage_records` (copy `raw_result` when present; the v4 contracts already allow it): routed to GX-10, proposed patch in the PR.
- `defects.py` is not in the owned list but is the only tool that writes a status transition; the `open → resolved` transition on `defect.verified` is the minimal declaration of this unit's own change (OWN DEPENDENCIES rule), guarded by `defects.verify_open`.

## Known base defects / env failures (not this unit)
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (adjudicated by the pinned gate); env: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (GX-ENV).
