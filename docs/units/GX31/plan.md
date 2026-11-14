# GX-31 plan

Goal: tier 2 in the train's judge path reuses a proof only when a verified v4 `gate.passed` matches the exact key the
train recomputes itself; anything else runs. Switch `train-reuse.reuse_attested_proofs` (true; false = today).

## Commits (dependency graph)
| # | Commit | Files (owned) | Depends on | Edge |
|---|---|---|---|---|
| 1 | audit | `docs/units/GX31/audit.md` | — | — |
| 2 | plan | `docs/units/GX31/plan.md` | 1 | real |
| 3 | switch: `config/registry/train-reuse.json` + generated module, `units/engine-train/unit.json` claims the new files, `CODEOWNERS` by `scripts/generate` | registry, generated, unit.json, CODEOWNERS | 2 | real (key needed by 4/5) |
| 4 | `scripts/lib/train_reuse.py`: `expected_key` (recomputed from git, `gate_batch.plan`, `gate_proof`, `gate_keys`, `gate_digest`) and `find` (verified source + every field); `scripts/tests/test_train_reuse.py`, `scripts/tests/train-reuse.test.sh`, `scripts/tests/covers/train-reuse.json` | new files only | 3 | real (reads the key) |
| 5 | `scripts/lib/train.py`: `Train.judge` asks `train_reuse` first on a commit whose prefix is known; a hit records a green run with the proof's `event_id` as verdict and runs nothing; tests in `test_train_reuse.py` (rebuild of an unchanged batch = 0 runs, one-byte change per input re-runs, switch off = today) | train.py, test_train_reuse.py | 4 | real |
| 6 | RETRO `docs/units/GX31/retro.md` | retro.md | gate | real |

Critical path: 1 → 2 → 3 → 4 → 5 → gate → 6, ≈ 10 + 5 + 10 + 25 + 20 + gate + 10 min. Commits 3 and 4 share no file and
could run in parallel; they are small enough that one writer is faster than briefing two sub-agents (stated choice).

## Key (GA-P02 strict, P-43)
`input_digest = gate_digest.input_digest(head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version)` with
`head_tree` = tree of the judged commit, `base_sha` = the batch base, `plan` = `dev` (gate-batch runs `gate-local --dev`),
`selection_digest = gate_proof.selection_digest(plan, gate_batch.plan(ROOT, base, heads, commit)['selection'])`,
`toolchain_id = gate_keys.toolchain_id()` (GX-28 attestation, E49), `gate_version = gate_proof.gate_version(ROOT)`.
A proof matches only if it is a `gate.passed` at the v4 proof version, pr null, `tier` = `gate-tier.batch`, from a
remote adapter that filters by trusted author association (the port re-validates `event_id`), and every field above
plus `input_digest` is equal. Any exception, missing input, file-log source or field mismatch: run.

## Premises
- P-43 (GA-P02, strict exact-key reuse) — CRITICAL, decided; this unit implements it.
- P-46 (GA-PG1, pinned verdict) — high; the verdict of record is `scripts/gate-dev --pr <n>`.
- Producer gap (audit finding 4): no tier-2 verdict reaches the repository channel on the base, so in production the
  lookup finds nothing and tier 2 runs (fail closed) until `gate_report` publishes repository-run verdicts (GX-12
  lesson (c), owner of `gate_report.py`). Radius low: it only delays the saving, never admits an unproven batch.

## Tests
- 3: `scripts/config check` / generator check, `scripts/structure-check`.
- 4-5: `python3 scripts/tests/test_train_reuse.py`, `scripts/run test train`.
- Final: one pinned `scripts/gate-dev --pr <n>`.

## Known base defects expected
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env tests `claude-session`, `root-identity`, `config`
(GX-ENV); TMPDIR flake class (GX-ENV).

Decision: D-070
Premises: P-43, P-46
