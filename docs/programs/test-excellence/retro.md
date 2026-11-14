# Program test-excellence: retro (wave 1, PR #742)

From the brief (00:58 BRT) to the accepted gate; times UTC.

1. **Brief.** Classes (a)–(e) and both named instances held.
   - #740's cause was a covers file owned twice plus an undeclared `requires` (`test_unit_check.py:185`), not an unowned file.
   - The brief missed the costliest items, which only the audit found: CODEOWNERS (30 of 76 PRs), the literal baselines (27 conflicting PR pairs), the 27-PR base-red, and a base over its bundle budget.
2. **Premises.**
   - Held: flat script-test discovery, a literal census that reaches nested dirs, covers globs that select a suite from its parts, a 0755 `--pr` checkout root.
   - Broke: NANO B4 (the known-defect route has covered every stage since GX-32), so TX11 was re-scoped.
   - Broke: TX24 → TX00 was a collision. My first program.v1 block also kept collision edges; A Torre caught it at 01:23, and revision 2 launched 12 units at 04:30Z.
3. **Timeline.** 04:02 PR; 04:16 audit; 04:20 plan; 04:24 TX00; 04:30 briefs; 04:34 backlog; 04:53 TX01; 05:03 pinned gate; 05:04 TX13 brief; 05:10 base merge of #746 (TX26); 05:09–05:14 evidence gates.
4. **Every failure, with its class.**
   - Own: numeric literals in my suite test.
   - Class fix: four flat `scripts/tests/*` globs blind to nested parts, all fixed in the TX00 commit.
   - Integration faults in TX01 as handed over, all four fixed:
     - a fixture cloned a bare repo whose HEAD named a branch never pushed;
     - its generated types, CODEOWNERS and asset entry were missing, and `scripts/prepush` itself reported all three;
     - it called GitHub directly, so I added the port operation `ForgeEvents.open_pulls` (D-069 item 7);
     - its tests used `'a' * 40` literals.
   - Env artifact: an evidence worktree under the 0700 scratchpad broke the dropped-uid probe; from a 0755 path it passed.
   - Waits: one gate slot, and the deadline changes made me stop the evidence gates once.
5. **Gate.**
   - **Run 1, `ca39a1e0`:** every stage PASS except `build (production)`. The base's own bundle was over budget (695469 > 695296), this PR had no web change, and the known-defect route excludes builds.
   - **Run 2, `2bce6497`, after the TX26 base merge:** the pinned verdict matched run 1, but the report-only run caught `prepush.test.sh` red. My test hard-coded TX26's old selector wording; I fixed it to derive the selection from `gate_script_tests`.
   - **That run exposed backlog X22:** the pinned verdict ran the base's 92 tests and never the 2 this PR adds. #742 is therefore held to a green report-only run too.
   - **Evidence gates** (#732 merge 270 s, #740 merge 236 s): red on the same base stage only.
   - The base fix #757 (D-072, `36692e98`) cleared that stage. The final gate is on the head that merges it (MERGE-READY comment).
6. **Lessons**, each with its owner:
   - (a) Briefs quote a failing check's full message (A Torre's brief template).
   - (b) `scripts/program check` compares `depends_on` with the plan's edge table (engine-coordinator).
   - (c) Globs over test directories come from one helper (TX25).
   - (d) Run `scripts/prepush` before every push (this PR's hook).
   - (e) Plan evidence gates and the final gate as a chain on a one-slot container (brief template).
   - (f) **The class this exposed.** A build or budget failure on the base had no route of its own. The known-defect route covers only test stages (`defects.stages`), and nothing else let the queue pass a red base stage. So one base-red, #658 pushing the bundle over budget at 27/10 10:21, stopped the queue, #742 first. It stayed hidden for 19 hours because PRs with scoped plans never build production. D-072 (`docs/process/blockers.md`) is the new evaluation step for exactly this: four questions before any action, three options. #757 applied it (a temporary ceiling) while TX13 (#756) fixes the cause. This program's gates are the first runs to prove it: the red came from #742's pinned gate, and the same gate went green after the D-072 action. Owners: D-072 (process); the train judging budgets on the merged result (train owner); X22 (gate pin).
