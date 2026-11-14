# GX-10 retro

Unit: gate.passed|failed v4 producer (proof fields, `.pass` fields, cost; `gate-proof.event_version`). PR #727, branch `mod/gx10`, base `mod/roadmap-integration` (eaeeb29d at launch, fbc09f28 merged in at 01:39 UTC).

## 1. Brief quality

- **Wrong premise: "the producer change lives in `gate_proof.py` and `gate-hooks/proof.sh`".** The GX-39 seam returns a payload, but the envelope is built in `gate_report.py:71` with no version, so `forge_events.default_version` always picks the `gate-contracts` pin (3). No change inside the two owned files can emit v4 with a one-key rollback. Resolved with a one-line edit in `gate_report.py` (passes `gate_proof.version_of(verdict)`), reported as a DECISION comment; the brief's acceptance line "gate_report.py untouched" is therefore not met by exactly one line.
- **Second seam gap: the `.pass` extras are a static string fixed at the proof hook**, before classification writes the scoped plan. The brief asked for `input_digest` in the `.pass` record; the design answer is a selection digest over the selection *request* (plan + batch selection), known at the hook, which with head tree, base sha and gate version determines the scoped plan.
- **Contract vs brief:** the brief says `rest_calls` "or null"; the v4 contract requires an integer (0 when nothing was counted). The brief says the v4 key was `forge-events.gate_event_version` in plan.md and `gate-proof.event_version` in plan-v2; plan-v2 was followed.
- `tier` is None for every non-tier-1 mode (gate_tier, until GX-11), and v4 requires 1..3: the brief did not say what a db/noite verdict should be. Chosen: v3 for any run that cannot be fully bound.
- `OU_GATE_VERSION` is set by `gate_pin.py` but unset by `gate_pin_handoff` before the proof hook, so the hook recomputes it with gate_pin's own recipe (tree of `scripts/` at the tooling commit).

## 2. Audit and plan

- P-42 (GA-P01, content-addressed proof) held: every input of `input_digest` is recomputable from git and the toolchain manifest; the test and a real-repo run show it.
- Plan held at 6 items; no sub-agents (one module chain 3 → 4 → 5, REAL edges). Item 4 got a second commit (literals, below).

## 3. Execution (UTC)

| Time | Commit / event |
|---|---|
| 01:27 | `fc52a204` audit skeleton; PR #727 opened as draft; STATUS |
| 01:33 | `7b65b4d7` audit; `a3c5b219` plan; DECISION comment on the seam gap |
| 01:34 | `643f5cef` registry `gate-proof.event_version` + generated module |
| 01:37 | `dc50032a` v4 producer + test (green first run) |
| 01:38 | `75f7f6ff` proof hook; `gate-local.test.sh` asserted the proof hook is a no-op (1 failure, own change: proof left the no-op loop as pin did for GX-05) |
| 01:39 | `f95598b6` base merge (GX-27, 6 commits) |
| 01:41 | `4530ca43` literals: structure-check refused 12 literal/hermetic findings in my two Python files (numbers 3, 4, 11-14, 1000, `/proc/`, `time.time()` in a test) |

Failure classes:
1. **Literal/hermetic scan found only by `structure-check`, not by the push guard** (`local-checks: 0 refusal(s)` on every push). Class fix applied to every occurrence in my files in one commit: versions come from the locked contracts, the CPU counter path is a registry key, proc(5) fields are named, milliseconds one constant, the test uses the shared fixed clock.
2. **Hook-shape test** (`gate-local.test.sh:161-163`) asserting a hook stays a no-op: expected for the owning unit; same shape as GX-05's.
3. A self-inflicted test-harness slip: `from test_gate_report_skips import SeamPayload` re-ran GX-39's TestCase in my file; changed to a module import.

## 4. Gate

One pinned run on `4530ca43` (`scripts/gate-dev --pr 727`, 01:41-01:45 UTC): `gate: pinned to fbc09f28`, scoped dev plan (db=0), 7/7 stages PASS (no GitHub Actions, generated drift, schema compat, secret scan tree/history, structure check, script tests 155 s), no known defect hit (none of KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 appeared), `GATE: PASSED`, evidence `gate.passed 30bbc943a0d5`, total 188 s (above the 180 s ceiling: a warning, D-064 (f)). The advisory run of the head tooling (version `2f6b1eef`) also PASSED in 28 s. As expected, the pinned run used the base's no-op proof hook, so that event is v3 and the `.pass` record has no extras; the head tooling's v4 output was checked on the real repo instead: `gate_proof.py bind` on head 4530ca43 / base fbc09f28 produced a `gate.passed` v4 that validates (lane `engine-lane`, `input_digest 756cdab9…`), and the digest recomputed from git and `toolchain_manifest.install_id()` matched. A second, docs-only gate run on the retro commit follows (P-01: the structure check reruns).

## 5. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| A seam module whose caller fixes the envelope version (or any field the module should decide) | Seam units (GX-39 style) list every call argument the downstream owner must control and expose it from the seam (`version_of`), with a test; a brief that says "the change lives only in X" is checked against the call site before launch | planning coordinator (brief template) |
| A hook seam whose extras are fixed before the data exists | Hook seams (GX-38 style) document *when* each value is known; extras appended at the end should be read from a file the hook names, not a string set early | GX-38 follow-up / gate-run lane |
| Literal scan runs only in `structure-check` | Add the literal and hermetic scans of changed Python files to `config/registry/local-checks.json` (the push guard) within its time budget | engine-commit-plan lane |
| Brief field types contradicting the locked contract (`rest_calls` null) | Brief template: field types are quoted from the contract, never paraphrased | planning coordinator |
| First real v4 event only after merge (the pinned gate judges with the base tooling) | Coordinator, right after merge: the next pinned gate on any PR must post a v4 `gate.passed` whose `input_digest` recomputes (`test_gate_report_v4.py` shows how) | coordinator |
