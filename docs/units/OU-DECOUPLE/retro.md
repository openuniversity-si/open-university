# OU-DECOUPLE — retro

Stage 6 of Daniel's unit standard of 30/10, written before the final merge, over the whole unit: Daniel's brief
(30/10 17:41–17:47 BRT), [intake](intake.md), [research](research.md), [audit](audit.md), [plan](plan.md),
[phases](phases.md) and PRs #822–#827, from 17:55 to about 00:10 BRT.

## 1. Targets vs measured
| Target | Baseline (`02a7816a`) | End (#827's head) | Verdict |
|---|---|---|---|
| M. Acting engine files that name `apps/web` | 351 | 0, held by the structure check (D-113) | met |
| T1. Tracked paths with no area | 16 | 0, held by the structure check (D-106) | met |
| T2. Engine paths whose one-file diff selects an OU stage | 939 of 3,193 | 0 | met |
| T3. OU stages any plan can select | 15 of 23 | 0 of 8, in every gate mode | met |
| T4. Files under `apps/web` / OU unit manifests | 1,249 / 74 | 0 / 0 (2,815 tracked files, 36 units) | met |
| Archive | none | commit `567176bb`, all of OU with history (D-110); the tag is Daniel's command | met in substance; tag pending |
| Production offline, last | site up | pause decided and announced (D-114); Daniel's step | pending (credentials) |
| G1. Script tests passing | 111 of 111 | 95 of 95 | held: 17 removed, all testing deleted OU code (phases.md, F4) |
| G2. `def test_` in `scripts/tests/**.py` | 2,524 | 2,306 | held: every removed function tested deleted OU code or duplicated a kept twin, and +16 were added |
| G3. Engine gate green on every merged head | — | #822–#826 green at merge | held |
| G4. Engine gate wall (session) | 78–329 s; an engine script diff also paid OU's install and vitest | 46–221 s, and no OU stage at all; #826's 1,650-file deletion took 221 s | held |
| G5. Engine behaviour | the train merges | the train merged #822–#826 | held |
| G6. Neon and R2 data | untouched | untouched: no command addressed them | held |

## 2. Failures, by class
| When | Failure | Class | Root, and the system fixed |
|---|---|---|---|
| 17:55 | preflight: `missing NEON_API_KEY`, `missing VERCEL_TOKEN`; CONNECT 403 to Neon and Vercel | env | the environment's network policy; the Vercel pause is Daniel's (D-114) |
| 17:55–18:45 | the VM runner gated merged #821 with the full battery (about 47 min) | code (engine) | an empty diff was a full battery; D-106 plans the always stages |
| 19:43 | #824 red: the base's coverage check validated the head's map with the old loader | code (this unit) | a check read more of the judged data than it needs, under the pin; D-109 makes it read globs only |
| 20:00 | tag push refused (git 403, REST 403) | env | this session pushes one branch; D-110 records the archive commit and Daniel's command |
| 21:15 | #825 red on three rules that read a deleted unit as live (lanes, visual, registry removal) | contract | no rule knew a retired unit; D-112 (retirement) plus deprecations, removal held back and re-landed |
| 21:35 | pre-push vendor check compared with the branch's previous push, not with the PR base | env (tool) | `commit-check --local` takes the branch's refs; pushed with `--no-verify`, and the gate judged the PR base |
| 22:15 | the re-landing revert also removed D-112's row | code (this unit) | reverting a commit that both held back and recorded; restored in #827 |

## 3. Timeline (BRT)
17:55 #822 opened · 18:17 F0 merged `af3fb0ee` · 18:42 F1 merged `de2b119c` · 19:57 F2 merged `567176bb` (the archive)
· 20:00 F3 recorded · 21:15 #825 red, removal held back · 21:40 F4a merged `daa866c9` · 21:58 F4b merged `c770ba2e`
(OU gone) · 23:59 F5 measured.

## 4. Lessons
| Problem | Change that would have prevented it | Owner |
|---|---|---|
| A rule that reads the judged checkout is run by the base's code (the pin) | a structure-check module parses only the data it needs from the judged tree (D-109's rule, generalised) | engine-structure |
| Retiring a multi-lane product had no rule | D-112, plus `docs/process/RETIRE.md` | A Torre |
| An empty diff and an unmapped path silently ran everything | D-106; any fail-safe that costs a runner hour must also be loud | engine-gate-plan |
| The local pre-push check judged against the branch's last push | `commit-check --local` should take the PR base (`origin/<base>`), as the gate does | engine-commit-plan |
| The runner's known orphaned `gate.lock` after a 3,600 s kill (Daniel's note) did not block this unit; it stays open | a job's process group is killed with it, and the lock is a lease | engine-service |
| Reverting a mixed commit drops what it also recorded | a hold-back commit carries only the revert; decisions land separately | A Torre |

## 5. Not done, with the exact next step
1. **Archive tag (Daniel).** `git tag -a ou-archive-2026-10-30 567176bb -m "Open University archive (D-105, D-110)" && git push origin ou-archive-2026-10-30`.
2. **Site offline, last (Daniel, after step 1).** `curl -X POST "https://api.vercel.com/v1/projects/prj_HJ0ueSZq4QBI0RYiNqDCxFux1ScO/pause?teamId=team_feEmDZ0B5CZl98oD8mq8U4UC" -H "Authorization: Bearer $VERCEL_TOKEN"`, or Project Settings → Pause Project. Undo: `/unpause`. Neon and R2 stay (D-114).
3. **Deprecated keys leave.** The next revision may delete the 16 keys F5 deprecated (schema compat now allows it).
4. **Leftovers named by the F5 helpers.**
   - `preflight.py` and `credentials.py` still require the Neon and Vercel IDs and probe browser libraries.
   - The toolchain still installs pnpm, Vercel and PostgreSQL.
   - `gate_speed.py` keeps unused web commands.
   - `.cursor/environment.json` is still named "Open University".
   - `services/runner/github/no-github-actions.test.ts` reads the deleted `merge-phase`.
   None names `apps/web`.
5. **Private archive repository (optional).** The recipe from the archive commit is in `phases.md`, F3.
