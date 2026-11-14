# Live planning — hand runbook

Program record: [D-071](../domain/DECISIONS.md). Design: [design.md](../programs/live-planning/design.md). Plan:
[plan.md](../programs/live-planning/plan.md). Contracts: `contracts/events/plan.{changed,note,input,candidate}.v1.json`
([EVENTS.md](../process/EVENTS.md) › Plan events). This is the procedure A Torre follows by hand from the LP2 merge; code
(LP3-LP6) removes the hand work, it does not enable it. **PRs never wait for it: only the plan moves.**

## 1. The checklist (answer in writing, per input)

Most inputs end in "no change, recorded"; that is a valid decision. Write the answers that mattered (at most 10 lines) in
`judgment`.

1. What exactly is new, and how sure is it? (evidence, sightings, reproduced on the base or on one box only)
2. Who does it touch? Pending units, running units, the base, other programs.
3. What does doing nothing cost? Affected units × expected loss each (red runs, rediscovery, rework, conflicts) against the cost of acting.
4. Is there something I can do now that makes the rest go better or faster? A short prep unit; fix first and launch after; one brief line; apply a lesson; register a known/env defect; pull a later unit forward.
5. Does the graph still hold? Premises, dependencies, estimates, splits: reorder, re-split, merge, drop, defer, add or remove an edge.
6. What should launch next, and what should not yet? A targeted hold (named units, reason, release condition), never a global one unless the base or engine itself is untrustworthy.
7. For each running session it touches: reuse or redo? Default continue; rescope or redo only when the input makes the session's output wrong (design 2.4); at most one rescope per input.
8. Is it mine to decide? Scope, money, production, source of truth go to Daniel with the decision prepared; meanwhile apply the safest reversible option and carry on.
9. Robustness: what change makes this never need deciding again? A rule, helper, registry key, brief line or Padrão candidate, and who owns it.

## 2. Append a `plan.changed` line by hand

The log of a program is `docs/programs/<program>/plan-log.jsonl` on the branch `plan/live` (`planner.log_branch`): one
`plan.changed` payload per line, append-only, one writer (A Torre until the planner role exists), never a force push.

```bash
git fetch origin plan/live          # first time: git switch --orphan plan/live, commit, push
git switch plan/live && git merge --ff-only origin/plan/live
tail -n 1 docs/programs/<program>/plan-log.jsonl     # the head: its version n and its digest
```

Write the new line (version n+1, `parent` = `{"version": n, "digest": "<digest of the head line>"}`; version 1 has parent
`{"version": 0, "digest": ""}`). Fields: `repo`, `pr` (null), `sha` (null), `unit` (null), `premises`, `program`,
`version`, `parent`, `ops[]`, `inputs[]`, `judgment[]`, `intention`, `expected_effect`, `decided_by`, `reversible`,
`escalated`, `digest`. `ops[].op` is one of: `add_unit`, `set_unit`, `remove_unit`, `set_deps`, `reorder`,
`set_estimate`, `hold`, `release`, `brief_line`, `rescope`, `redo`, `continue`, `register_defect`, `apply_lesson`,
`escalate`, `note`; `unit` names the unit and `args` the fields set (a hold carries `reason` and `release_when`).

The digest is the hash chain: sha256 of the canonical JSON of the line **without** its `digest` field (sorted keys,
separators `,` and `:`, UTF-8), which includes `parent.digest`:

```bash
python3 - <<'PY'
import hashlib, json, sys
line = json.loads(sys.stdin.read())
line.pop('digest', None)
print(hashlib.sha256(json.dumps(line, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())
PY
```

Then write the line with that digest, check it with `python3 scripts/lib/event_contracts.py check` against the schema (wrap
the payload in an envelope, or compare field by field with `contracts/events/plan.changed.v1.json`), commit, and push
(`git push origin plan/live`). A non-fast-forward means another writer appended: fetch, merge (merge commit), recompute
`version`, `parent` and `digest`, push. A stale `parent` is always refused; never edit an earlier line.

## 3. Read and fold by hand

```bash
git show origin/plan/live:docs/programs/<program>/plan-log.jsonl | jq -r '[.version,.decided_by,.intention]|@tsv'
scripts/program check <program>      # the version-0 graph in plan.md (program.v1 block)
```

The live plan is the `program.v1` block of `plan.md` (version 0) with the `ops` of lines 1..n applied in order:
`add_unit`/`set_unit`/`remove_unit`/`set_deps` edit the graph, `reorder` changes order inside a wave, `hold` blocks a
launch until its `release_when` holds (a `release` op lifts it), `brief_line` adds a line to the named units' briefs,
`rescope`/`redo`/`continue` are the decision for a running unit. To see the plan at version k, apply only lines 1..k.
Before each launch read it (a launch outside it is entered as a `plan.changed` with `decided_by: A Torre`). The folding in
code is `scripts/lib/plan_live.py` (`fold(plan, changes) -> plan`, with a fixture); until LP3 merges it raises
`NotImplementedError`.

Pass-on from a running session and triage: `scripts/plan note|input|triage` (stubs until LP4); until then, enter the same
information as `inputs` in the line you write.

## 4. Registering tests

An LP unit registers its test with its own sidecar `scripts/tests/covers/<test>.json` (fields `script` and `covers`;
gate-excellence GX-08, D-B3), one new file per unit, so units never collide: the sidecars are the map
(the aggregate `gate-script-tests.json` left), and a `*.test.sh` never carries header lines for it. If GX-08 has not merged when an LP unit
launches, the coordinator decides then.

## 5. Role

The planner role of LP6 (`planner_role.py`, the wake port `adapters/planner_wake.py` and its Claude adapter, the
`planner-lp6.*` keys and the switch `planner.enabled`) left with VAZÃO F15: the switch stayed false and the plan log
branch never received a `plan-log.jsonl` line from it. A Torre judges the candidates in its own session, answers the §1
checklist and appends by hand (§2), with `decided_by: A Torre`.
