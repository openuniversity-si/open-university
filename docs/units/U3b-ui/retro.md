# U3b-ui retro (whole unit, from the brief to the accepted gate)

Facts with evidence. Timeline from the branch commits (author times are session times, UTC).

## 1. Brief quality
- Missing: the work-branch name conflicted (brief `mod/u3b-ui-addresses`, session-designated `claude/u3b-ui-addresses-w6a1su`). Used the designated one; recorded in the PR body.
- Ambiguous: "replace every import that crosses a unit boundary with `@ou/<target>`". The brief did not say the file form (`@ou/<id>/<path>`) is the only importable form, because no manifest has `contract.entry`. The merged lanes had already chosen it (`3c0ffb84`, `2b34b62b`); I followed them.
- Wrong premise I took on: `scripts/units addresses` shows `addressable: false` for all ten ui units. I first read that as "no address". It means "has an address and no path importer left" (`unit_addresses.scan`). Corrected from the code before the plan.
- Missing from the brief: the list of build seams that rewriting must not touch (`next.config.ts` turbopack `resolveAlias`, `vitest.config.ts`). The brief's "mechanical" framing did not cover them.

## 2. Audit and plan
- Premises that held: P-03 (addresses resolve; all 25 target units are in the map), P-13 (a single `unit_addresses.check` catches leftovers).
- Premise that broke: "a rewrite is behaviour-neutral". It is not, for the seam alias `@tower/playback-engine` (see 3).
- Plan change: none to the commit graph. Added a step-6 census record (`census.md`) and a mid-run base merge check.

## 3. Execution, failures and root causes
| # | When | Failure | Root-cause class | Fix |
|---|---|---|---|---|
| F1 | commit 3 (`35522779`) | none in the commit's own checks (tsc 0, touched test 7/7) | — | — |
| F2 | commit 5 | none | — | — |
| F3 | commit 6 (`2b6a24be`) | `ui-lesson-row` unit battery red: `lesson-row.test.ts` asserted the alias text `@/ui/lesson-row/CourseProgress` of `PlayerRail.tsx` | code: a test asserted import text; instance count from grep = 1 | assertion updated to the address (same commit) |
| F4 | after base merge (`3af7b3dc`, U4 #614) | none; address map, `units check` and tsc re-checked | — | — |
| F5 | gate run 1 (head `3af7b3dc`, 761 s) | e2e smoke: 12 player/progress specs timed out on `__towerFakePlayback` | code: a build seam bypassed. `next.config.ts` resolves `@tower/playback-engine` to the fake engine in the test build; my rewrite pointed `usePlayback.ts` at `youtube.ts` directly | commit `c7c9a661` restores the alias; re-gate green (370 s) |
| F6 | session | a `cat >` without input waited on stdin until the 600 s tool timeout (cost ~10 min) | process: a command with an empty heredoc | killed; rule: never start a write without its content |

Where the time went: the e2e smoke stage was 408 s in run 1 and 67 s in run 2 (the failing specs each waited the full 30 s timeout). Gate total 761 s and 370 s, both over the 180 s ceiling (D-064 f), reported as warnings.

## 4. Gate
- Runs: 2 on the PR's head line (`3af7b3dc` red, `c7c9a661` green). One more is needed for the retro commit, see the PR comment.
- Stage classes: run 1 red only at e2e smoke, class `code`. Run 2 green in every stage.
- Known defects hit: none.

## 5. Lessons (each with a concrete change and an owner)
1. **Rewrite tools must skip build seams.** The address rewrite should refuse to rewrite any specifier that a build config remaps (`next.config.ts` `turbopack.resolveAlias`, `vitest.config.ts` `resolve.alias`). Proposed check: `unit_addresses.check` reads those maps and reports a rewritten specifier that is also a seam. Owner: engine-addresses (U3a/U0 owners). Until then, the per-lane rule in the brief must list the seams.
2. **Verify a rewrite by resolution, not by text.** The resolve check (`unit_map.Code.resolve_import` on the new spec) caught no problem here because the seam was not a file-level mismatch; it resolved to the real file. The class check is the one in lesson 1. Owner: same.
3. **Grep for asserted import text before rewriting.** Tests that assert on source text (`toContain("@/ui/…")`) break on any rewrite. Rule for the brief template: list the test files that assert import text, found by grep, in the plan. Owner: the brief template (program coordinator, CO1).
4. **Read a flag's definition before acting on it.** I misread `addressable`. Rule: the units README (or the `addresses` help text) must say `addressable = address and no path importer left`. Owner: U3a (units docs).
5. **Never start a write without content.** Owner: the session process (no tool change needed; stated in the lane's rules).
6. **Gate time over the ceiling.** 761 s and 370 s against 180 s. Not caused by this PR, but this PR hit it. Owner: the gate (T1/H0 performance stage).
