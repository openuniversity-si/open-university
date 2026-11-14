# TX21 — audit

Launch 2026-10-28 (TX-PROGRAM, test excellence, plan revision 2). Base `mod/roadmap-integration` at 891b835ae.
Decision D-070, Premises P-46. Lane engine-lane. Never merged by this session.

## Evidence re-verified on 891b835ae

| Brief claim | Holds? | Proof |
|---|---|---|
| #740 (head 8f6ba426) red on a double claim | yes | `unit_check.check` on a worktree of 8f6ba426: `scripts/tests/covers/gate-timing-report.json belongs to 2 units (engine-gate-plan, engine-gate-report); a file belongs to one unit (D-067 (6))`. A second, unrelated error on that head: `units/engine-gate-report: imports unit engine-slo without declaring it` (not ours). |
| test_unit_check.py:185 asserts the repository is clean | yes | `scripts/tests/test_unit_check.py:183-185` (`Repository.test_d064d_…`), message built in `scripts/lib/unit_check.py:44-45` (`ownership()`). |
| engine-gate-plan owns `scripts/tests/covers/**` by glob since GX-38 | yes | `units/engine-gate-plan/unit.json:25`, commit 1fe9fa56c. #740 adds the exact path at `units/engine-gate-report/unit.json:30` and its test at line 41. |
| The message names neither the line to remove nor the owning glob | yes | `unit_check.py:44`: only the path, the count and the unit ids. |
| CODEOWNERS is generated and committed, one row per manifest glob | yes | `scripts/lib/generate_codeowners.py:29-36`; `config/registry/generate.json:56-65` (`committed: true`); 953 rows today. |
| 51 PRs since 26/10 edited it | yes | `git log --since=2026-10-26 --first-parent origin/mod/roadmap-integration -- CODEOWNERS` → 51. |
| Every lane maps to the same identity | yes | `scripts/config get generate.codeowners_identities`: all 18 lanes → `["@the-owner"]`. |
| Only production files need an owner | yes | `unit_check.py:46-48` uses `units.production(...)`; `units.test_globs` contains `scripts/tests/**`. |

## Findings

1. **Companions are hand-claimed.** Every `scripts/tests/<t>.test.sh` has `scripts/tests/covers/<t>.json`
   (`gate-tests.covers_dir`, `scripts/lib/gate_script_tests.py:30-32`; 90 tests, 90 covers). Ownership is pure glob
   (`units.py:units_of`, `unit_check.py:40-41`), so the covers file is owned by whoever claims it: today the central
   `covers/**` glob of engine-gate-plan, which collides with any unit that also lists its own sidecar (#740).
2. **The double-claim error is not actionable.** `unit_check.py:44` does not say which manifest line to remove, nor
   which rule already owns the file.
3. **The unowned-production error is not actionable.** `unit_check.py:47` says "add it to the manifest of the unit that
   owns it" without naming a candidate; the units owning the file's siblings (same directory) are the obvious answer.
4. **CODEOWNERS churns on every manifest path.** `generate_codeowners.render` writes one row per manifest glob, so every
   path added to any manifest adds a row. Replay over the last 80 first-parent merges of the base (scratch script,
   manifests and `git ls-tree` at each merge): the legacy file changed on 26 of 79 consecutive pairs.
5. **Readers of ownership.** `units.unit_of` is read by gate_select, gate_batch, defects, literal_census,
   threshold_check and the generator; `train_ownership.UnitOwnership` (train, pr_ready, quarantine) has its own glob
   reader at a commit. A companion with no claim adds no lane there (`lane_of` ignores files no manifest covers), so a
   derived companion never makes a head two-lane; its lane comes from its `.test.sh`, normally in the same diff.

## CODEOWNERS: what "minimal equivalent" can and cannot do

The brief requires the same effective owner set for every tracked path, including the empty set of an unowned path
(docs, unclaimed tests). Under that strict equivalence a directory-tree cover with one default per directory (a
`/dir/` row where the default changes, a file row for each exception, a row with no owner where an unowned region
starts) is minimal: 953 → about 130 rows today, and a path added to a manifest inside a region whose default is
already that owner changes nothing. Replay: 21 of 79 pairs changed instead of 26. The rest are owned files added
inside an unowned-majority directory (config/registry, contracts/events, docs/*) or unclaimed tests in an owned one:
the owner of that path did change (none ↔ lane), so strict equivalence must show it.

Removing that remainder means giving unowned paths a fallback owner (one `* @the-owner` row, zero churn while all
lanes share an identity): a change of who owns ~900 non-production paths. That is a source-of-truth decision, not
ours; it is reported as a proposal, not taken.
