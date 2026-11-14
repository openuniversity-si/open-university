# U3b retro: site-lane imports to `@ou` addresses (PR #581)

Covers the whole unit, from the brief to the accepted gate. Times are commit times (UTC, 2026-10-27).

## 1. Brief quality

- Missing: the brief said "run `scripts/unit-battery <id>`" as tier 1 and also "merge only if gate-dev is green". It did not say which one governs when they disagree. I ran both; the battery did not exercise the gate's node step, so it passed where the gate failed.
- Ambiguous: the work branch. The brief named `mod/u3b-site-addresses`; the harness named `claude/u3b-site-addresses-abjhuw`. I used the harness branch and said so.
- Ambiguous: "merge if green" against AGENTS.md "do not merge your own PR". The brief's explicit instruction was followed (see the PR comment for the decision).
- Wrong: the brief's commands use `gh api` and `gh pr merge`; this environment has no `gh`, so the GitHub MCP tools carried the PR work. The gate and merge helper scripts still ran.
- Wrong: `scripts/units` is a bash script; calling it with `python3` gave a syntax error at line 4 (`set -euo pipefail`). Not in the brief; cost one command.

## 2. Audit and plan

- Held: the U3a report (`scripts/units addresses --json`) lists the cross-unit importers per target, and the address map is generated in `tsconfig.json`. A scan of owned files found 52 cross-unit specifiers: 48 rewritten, 4 gaps. The gaps (web-build's `next.config.ts`, a content JSON, two `platform/db/testing` files with no owning unit) are listed in the PR body.
- Broke: the plan said each rewritten commit is "green alone". Commit 3 (site-domain) was green on the unit battery but not on the gate: the gate runs `node scripts/site-health.ts` directly, and Node does not read the tsconfig `@ou/` map. The plan did not list the gate's node-run steps among the things to check per commit. Fixed forward in commit 5, since history was not rewritten.
- Plan change: a fifth commit (`site-health` back to relative imports for the node step) and this retro. The plan graph was otherwise unchanged.

## 3. Execution (timeline)

| Time | Event |
|---|---|
| 06:46 | Audit commit (`62fbb54c`), plan commit (`1f73ff82`), pushed. Baseline batteries green (site-domain 28/13, site-server 16/4). |
| 06:47 | Commit 3 (`d7fe6eb1`): 25 specifiers in 10 files, site-domain. Battery green, census unchanged. |
| 06:48 | Commit 4 (`1be46309`): 23 specifiers in 11 files, site-server. Battery green, census unchanged. Draft PR #581 opened (after the first push, as the brief requires). |
| ~06:49–06:54 | Gate run 1 on `1be46309`: FAILED in unit tests (`ERR_MODULE_NOT_FOUND: @ou/kernel-limits` from `site-health.ts`, run by node). 314 s. |
| 06:54 | Commit 5 (`62355828`): two specifiers back to relative. Module graph resolves in node. Battery green. |
| ~06:55–07:00 | Gate run 2 on `62355828`: PASSED in 312 s (ceiling warning, 180 s). Pass record written. |

## 4. Gate

- Runs: 2 (`gate-dev --pr 581`). Run 1 failed in one stage (unit tests, class `code`); all other stages passed. Run 2 passed every stage.
- Known defects hit: none of the timing-sensitive tests named in the brief. Performance and structure stages passed in both runs.
- Wall time: 314 s and 312 s, both over the 180 s ceiling (D-064 f). The gate prints a warning; it is not a failure. Stage times are in the PR comments.

## 5. Lessons (concrete change, and owner)

1. **Node-run entry points and aliases.** The class: a file reached by `node <script>.ts` imports an alias that only tsc and vitest resolve. Immediate fix: commit 5. Class fix (not yet done): a gate or structure-check rule that refuses an `@ou/`, `@/` or `@tower/` specifier in any file in the import graph of a `node` step. Owner: the gate owner (engine-gate); it needs its own decision because it changes a gate. Until then, the unit battery is not enough for this lane: the rewrite must also run `node scripts/site-health.ts --fixture` (or the gate's node step) before push. Added to the plan template for the next U3b lanes.
2. **Battery versus gate.** The battery is the tier-1 check, not the whole gate. A tier-1 pass does not prove a node step. Owner: U3a (units battery), to list the gate's node steps for each unit it covers.
3. **Brief: branch name and merge rule.** The brief's branch name and the harness's designated branch differed. Owner: the wave maestro. Rule to add: the brief names the harness branch, or states which wins.
4. **Brief: gh vs MCP.** The brief's `gh api` commands do not work in this environment. Owner: the wave maestro. Rule to add: name the MCP tool calls, or the REST paths, that work here.
5. **Gate ceiling.** Both runs exceeded 180 s with no change to the gate's stages. This is not from this PR. Owner: the gate owner (performance budget, D-064 f). Not fixed here.
6. **Documentation of `scripts/units`.** Running it with `python3` failed; the docs do not say it is bash. Owner: U0 (units), a one-line note in `docs/architecture/UNITS.md`.

Follow-ups not done in this PR: (1) the gate check from lesson 1; (2) the 4 gaps listed in the PR body, for their owners (web-build, content/site, platform db testing, and the `site-server` address, which stays unaddressable because its home holds `site-domain`).
