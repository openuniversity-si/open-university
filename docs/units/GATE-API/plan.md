# GATE-API: plan (mirrored in the PR description)

Decision: D-070 (gate excellence program). Findings: [audit.md](audit.md). Written 20:55 BRT 28/10.

## Commits

- [ ] 1. The unit record: `audit.md` (the concept, what #780 already has, what it does not) and this file.
- [ ] 2. Take #780's items 2 and 5 onto this branch unchanged: the stage order (`gate-stages.json`,
  `gate_policy.PREREQUISITES`, `gate-areas.json`, `test_gate_graph.py`) and `docs/units/GATE-VERDICT-API/merge-tree.md`.
- [ ] 3. The API: `scripts/gate-verdict`, `scripts/lib/gate_verdict.py`, the `scripts/run gate verdict` line of
  `run.test.sh`, `config/registry/gate.json` keys (+ the generated registry module), `units/engine-gate-run/unit.json`,
  `scripts/tests/test_gate_verdict.py` + `gate-verdict.test.sh` + `covers/gate-verdict.json`.
- [ ] 4. The rule: `docs/padrao/v5/` (v4 plus `gate-verdict.md`) and `docs/operations/gate-verdict.md`; the test reads
  the exit table of the docstring and of `gate-verdict.md` and requires both to match the code.
- [ ] 5. `gate pin` in `gate_classify.DRIVER_STAGES` (so `ENV_STAGES`), with a test.
- [ ] 6. Proof on three real heads of tonight (one passed, one failed, one with no record): `proof.md`.
- [ ] 7. Retro and the verdict of record: `retro.md`, then `scripts/gate-dev --pr 800` on the final head.

## Graph

```
1 -> 2 -> 3 -> 4
          3 -> 5
          3 -> 6 -> 7
```

One committer, one commit per push. 2 goes before 3 only because the API documents the stage order it runs; 5 is
independent of 3 in code but is ordered after it so the unit's API lands first.

## The API (item 3)

`scripts/gate-verdict --head <sha> [--base <sha>] [--pr <n>] [--no-run] [--json]`, exit 0 PASSED, 1 FAILED, 4
UNOBSERVABLE, 64 usage. Steps, each failing closed to 4:

1. Read the input: the head commit (fetched); with `--pr`, the PR (bounded retries, `gate.verdict_read_*`), whose head
   must be the asked head; the base tip the pin will judge against (the PR's base branch, else `gate.batch_base_ref`).
2. Bind: the pinned tool root (`gate_pin.ensure`), then its `gate_proof.py bind --plan dev`: the `input_digest`.
3. With `--pr`, the metadata check live (P-42); red is answered FAILED at once, never recorded.
4. Tier 1 (F4): a record of this head and digest answers; `--no-run` without one exits 4.
5. Run `scripts/gate-local --dev` (`--pr N`, else `--sha <head>`) with a fresh `GATE_REPORT_DIR`; its output goes to
   stderr, the answer to stdout. Judge the report (audit F3), check the pinned base, record (decisions 1, 5).

Tests (no network, fixture repositories and injected seams): usage; every exit; a recorded pass and failure returned
without a run; `--no-run` with no record, an expired, a malformed and a foreign record; tier 2 and 3 neither read nor
write; an env-only failure answered and not recorded; an abort, a missing report, a contradicting report; a red metadata
check answered without starting the gate; a moved base rebound; the JSON shape; the literal-free exit table.

## Premises

| Premise | Status | Blast radius |
|---|---|---|
| P-42 proof content-addressed, metadata always reruns | confirmed, high | the metadata check is run live on every PR call and never recorded |
| P-43 / D-070 (b) tier 2 never reuses box-local markers | confirmed, high | the store refuses tier 2 and 3; wrong, the train gains nothing here, never a false pass |
| P-46 the pinned gate on the base tip judges | confirmed | the binding is computed in the pinned tool root; this PR's API judges only after it merges |

None is CRITICAL: no production, money or source-of-truth change.

## Cheapest useful effort

Action: the final `scripts/gate-dev --pr 800` on the final head (item 7), plus the gate runs the proof needs (item 6).
Cost: one gate run each, about 3-10 min wall; editing `scripts/gate-*` makes the run carry the full script suite.
Requirement: A Torre needs the merge door to show the API turns no other stage red before the train takes the PR.
Cheaper rejected: only the targeted unittest modules (they prove the API, not the plan around it); `gate-quiet` (the
full legacy plan, heavier, and not the merge door).
