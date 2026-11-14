# GATE-API: audit

Unit: the gate is an API that runs the tests and returns the result (engine-gate program, owner A Torre). Launched
28/10 20:25 BRT on Daniel's words of 20:22: "É simples: o Gate é uma API que roda os testes e devolve os resultados,
seja positivo ou negativo." (simple: the gate is an API that runs the tests and returns the results, positive or
negative). Passing or failing is the same call; the answer is the payload.

Base: `mod/roadmap-integration` at 069145b9 at launch. Branch: `claude/gate-api-test-verdict-m9zfzh`, PR #800.
Decision cited: D-070 (gate excellence program). Takes #780 (`mod/gate-verdict-api`); replaces the client of #797
(GATE-WAIT, closed by Daniel at 20:21: "Mate o GATE-WAIT").

Read-only audit, 20:30-20:50 BRT, direct reads of the base and of both branches. No gate was run.

## Claims checked

| Claim | Evidence | Verdict |
|---|---|---|
| #780 has its items 1, 2 and 5 done | 57e89a6b (plan), 3d19c9b8 (stage order, 4 files), 7f29e564 (`merge-tree.md`, 30/30); head 97055161 is a base merge | holds |
| #780 items 3, 4, 6 are not written | no `gate_verdict.py`, no `deterministic` change, no unobservable state on 97055161 | holds |
| a recorded result exists per head, keyed by what it judged | a pass leaves `.gate/records/<head>.dev.pass` with `base_sha`, `toolchain_id`, `gate_version`, `input_digest` (`gate_proof.pass_extra`); a failure leaves only `reports/<head>/dev-<ts>/stages.json`, which has no base, toolchain or digest | half: only a pass is keyed, and nothing reads it by its input (F2) |
| tier 2 and 3 never read or write the box-local store | `gate-tier.cacheable_tiers` = [1]; `gate_tier.cacheable`; D-065 (5), D-070 (b), P-43 | holds (F4) |
| `classify('gate pin', 'GnuTLS handshake failed')` returns `code` | run on 069145b9 with `scripts/lib` on the path: `'code'`; `'cannot read PR #12 head/base (exit 1)'` too | holds (F7) |
| #797 left a rule worth keeping | `docs/padrao/v5/gate-wait.md` on `mod/gate-wait`: the wait is the last step, a refusal is a task, at most three waits, exit 4 never a refusal | holds; its client read a verdict another process produced (F8) |

## Findings

**F1. The gate already measures; it does not answer.** `scripts/gate-dev --pr N` runs `gate-local --dev`, pinned to
the tip of the PR's base branch (GX-05, `gate_pin.resolve`), and ends with exit 0, 1 or 2 and a report directory.
There is no call that says "here is the head, give me the result", and no call that returns a result already measured.

**F2. The input a result was measured on is known only inside the run.** `gate_proof.bind` (the `proof` hook) fixes
`input_digest` = sha256 of [head tree, base sha, plan, selection digest, toolchain id, gate version], where the gate
version is the tree of `scripts/` at the pinned base tip and the toolchain id is `gate_keys.attestation()` (installed
versions plus the effective registry). It is computed in the pinned tool root; computed in the invoking checkout it
would differ whenever the head changes the registry (#780 F6). It reaches the `.pass` record of a pass and the v4
event; a failure keeps none of it on the box. The only reader of `.pass` (`ship_tail.record_ok`) checks sha and kind.

**F3. The exit code alone cannot tell a failure from a run that never judged.** `gate-local` documents 0 pass, 1 fail,
2 setup error, but `driver_abort "local database" ... 1` exits 1, and a pin that cannot read the PR writes no report at
all (`driver_abort`'s second GET uses `--jq .headRefOid`, which `github_api._jq` does not implement, so the sha stays
empty and no report directory is chosen; #780 F8). An aborted run with a report has `abort.json` and `aborted` in
`stages.json`. So the answer is read from the report: a pass needs exit 0 and a `PASS` report, a failure needs exit 1,
a `FAIL` report and no abort; anything else is unobservable, never a result about the code.

**F4. The tier decides who may use a recorded answer.** `gate_tier.derive`: `--pr` is tier 1, `--sha` without `--pr`
is tier 2 (the train's batch), `--tier3` tier 3; a run exports `OU_GATE_TIER` bound to its tooling. Tier 2 reuses only
an exact attested proof, never box-local markers (D-065 (5), D-070 (b), P-43). The API therefore keeps its records for
tier 1: a call without `--pr`, or one made inside a tier-2 or tier-3 run, runs the gate and neither reads nor writes them.

**F5. The PR metadata is never part of a recorded answer.** P-42 (confirmed, high): the proof is content-addressed
(tree, base, toolchain) but the structure/metadata check always reruns. The PR body, comments and push history change
without the head changing. So a recorded answer for a PR covers every stage but `pr metadata`, which the API runs live
first (`structure-check --metadata`, about 5 s, no install). A red metadata check is answered at once, without starting
the gate: the early stop #780 (F1, F2) moved out of GK1, which stays unchanged inside the gate.

**F6. An environment failure is not a function of the input.** A red stage of class `env` (a network read, a missing
library) says nothing about head, base or toolchain. Recording it would return the same failure for the same input after
the machine recovered. A failure is recorded only when one of its red stages is not `env`.

**F7. A failed pin read is classified as the PR's own failure.** `gate_classify.DRIVER_STAGES` lacks `gate pin`, so
`pin.sh`'s `driver_abort "gate pin" ...` prints `GATE-CLASS: gate pin<TAB>code`, against the rule written above the set
("a driver abort happens before the code under test runs ... always ... env"). The train halts only on `env` and
`contract` (`train.halt_classes`) and bisects and ejects on `code`.

**F8. #797's client is dead, its rule is not.** `scripts/gate-wait` blocked on a verdict another process would publish
(the forge's merged flag, `tower/gate` status). With an API that returns when the judgment does, there is nothing to wait
for. The rule survives: the call is the last step of a unit; a failure is a task, at most three rounds in one turn; an
unobservable answer is retried, then reported, never treated as a refusal. Padrão v5 does not exist on the base (v1, v3,
v4); #797's v5 was v4 plus one rule file. The active version (`coordinator.padrao_version`) is not this unit's to move.

**F9. Every literal of the API is a registry key.** The literal census (LT1, `literal_census.py`) fails a unit that
spells a number other than 0, 1 or -1 more often than its base does, tests included. The exit codes 4 and 64, the record
lifetime and the read retries go into `config/registry/gate.json`, and code and tests read them there.

**F10. The shared config store refuses every read in its default mode (environment, not this unit).** The GitHub change
store holds a `premise.blast` event whose producer `scripts/premises` (`premises.producer`) fails the envelope pattern
`^[a-z][a-z0-9_.-]*$`, so `config.get` raises `StoreError`: `scripts/cloud/setup.sh`, `.githooks/pre-push` and any tool
on the default store fail. `OU_CONFIG_STORE=file` reads the checkout's log instead; the gate already does (D-069 item 5),
and so does the API. Reported on #800; the fix is an env patch, not this PR.

## Decisions taken (decide, then report)

1. The record is the API's own, written by the API after a run it started, through the storage port (`adapters/storage`)
   under `gate.verdict_store_dir`, one per head and `input_digest`. Its key is the gate's own `input_digest`, bound by
   the pinned tooling's `gate_proof.py bind` before the run (F2); the base the pin printed (`gate: pinned to <sha>`)
   is checked against it after the run, and a moved base is rebound, never recorded under the wrong input.
2. A recorded answer is served on an exact head and digest match within `gate.verdict_ttl_s`; a malformed, foreign,
   expired or future record is a miss. `--no-run` answers a record or exits 4; it never starts the gate. With `--pr`
   the metadata check still runs live (F5); the stages in `gate.verdict_live_stages` are never recorded.
3. Tier 1 only (F4): the store is read and written only when the call's tier is in `gate-tier.cacheable_tiers`.
4. The answer is read from the report, fail closed (F3): exit 4 for an abort, a missing or contradicting report, a gate
   that cannot start, a PR that cannot be read or whose head is not the asked head, an explicit `--base` the gate cannot
   judge against (a run always pins the tip), and an unattested toolchain.
5. A failure whose red stages are all `env` is answered and not recorded (F6).
6. `gate pin` joins `DRIVER_STAGES` (F7); item 5, pinned by a test.
