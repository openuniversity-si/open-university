# GX-02 (+ GX-06) retro

PR #695, branch `mod/gx02`, base `mod/roadmap-integration` (`4bc4dd04` at start, `60392c0c` merged in at `0aa26798`). Commits 1-8, one per push, through the post-commit push guard.

## 1. Brief quality
- **Two branch names.** The brief named `mod/gx02`; the harness named `claude/train-halt-env-contract-vwd07q`. I took `mod/gx02`, which is also the session's outcome branch. A brief should name one branch, and the launcher should give the harness that same name.
- **Expected base.** The brief expected base `25c6f7a8` "or later"; the real tip was `4bc4dd04`. That was harmless.
- **HALT and RESUME.** A HALT (14:57) and a RESUME (15:04) came before any work, so no time was lost.
- **Scope change mid-flight.** Plan-v2 (15:20) absorbed GX-06 after six commits had been pushed. The 8-commit cap then forced all of GX-06 into one commit (7). A scope change after launch should restate the commit budget, or let the absorbed unit's commits count apart.
- **Wrong path assumption.** The brief cited `gate-local:21,65-67` for "the tooling is the checkout that runs it" but did not say that the base-tip tooling's *Python modules* (the hermetic `sitecustomize` imports `config`) also come from the base. That gap caused finding 3.1.
- **Contradictory specs.** The brief said `train.halt_classes=[]` "restores eject-on-anything", and `train.tier2_timeout_s`'s registry description said a timeout "counts as red (class env)". Item 4 first classed a timeout as `code`. Item 7 made it `env`, following the registry.

## 2. Audit and plan
- **Premises.** GA-P05 held (`eaa408de` was not on the base). P-18 held: the switch is the rollback. P-21 and P-33 were added by plan-v2.
- **The cherry-pick.** It applied with no conflict. The patch-id equals `eaa408de`'s.
- **Plan changes.** The plan changed once (items 7 and 8, after plan-v2). `plan.md` and the PR body were updated in commit 7.

## 3. Execution (UTC)
| Time | Commit | Note |
|---|---|---|
| 18:06 | `1e0faded` (1) | Cherry-pick. The post-commit hook pushes at once: the commit message's `Claude-Session` typo could not be amended. |
| 18:07-18:08 | `6699c216`, `82343326` (2, 3) | Audit and plan. |
| 18:10 | `8a7d1671` (4) | Class line in CommandGate. `test_battery.py`'s fake tier-3 gate had the same bare-`FAIL` pattern and was fixed as a class (2 places). |
| 18:12 | `55a04ea9` (5) | `train.halt_classes`, `env.drift`. |
| 18:14 | `3a5785f0` (6) | Docs. **Failure 3.2** fixed here. |
| 18:26 | `32e10def` (7) | GX-06 and **failure 3.1** fixed here. |
| 18:3x | `0aa26798` (merge) | Base `60392c0c` merged in. The push-guard timed out once; `push_guard.py push` retried it. |
| (8) | this commit | `train.enabled` default true, retro. **Failure 3.3** fixed here. |

Failures, each with its root-cause class:
- **3.1, base-tip gate red on `train-role.test.sh`** (`config: train.halt_classes is not a registered parameter`). Class: under the base-tip gate, the hermetic `sitecustomize` imports the *base's* `config` module, and `config.get(name)` without a root reads the base registry, which lacks every key the head adds. Fix: one helper, `engine_role.setting(name)`, reads this checkout's registry, and every train-module and test read goes through it (`gate_classify` already did this by root). The same latent class sits in every other module that adds a registry key and reads it without a root. That is the owner's to fix generally (engine-config, probably in `config.get` itself); see lessons.
- **3.2, LT1 literal census** (new numbers and durations in tests, `group(2)`). Class: the post-commit push guard pushes at commit time, so `structure-check` has to run *before* `git commit`, not before the push. Commits 4 and 5 went out unchecked. Fixed in 6 by deriving sizes from the registry.
- **3.3, `test_config_api` red after the default flip** (`train.enabled is already false/true`). Two causes. (a) The test assumed the default off. (b) My first refusal check read `config.store_kind()`, the env name, not the store in use, so a process that had chosen its own adapter while `OU_CONFIG_STORE=file` was set would be refused wrongly. Fix: the refusal checks `isinstance(store.port.adapter, FileAdapter)`. The test writes with `root=ROOT`. Every changed test was run in three modes: plain, `OU_CONFIG_STORE=file`, and base-tip tooling (`PYTHONPATH=<base>/scripts/lib/hermetic`).

Dead ends: none. Waits: the two gate runs (about 2.5 min each), run in parallel.

## 4. Gate
- **Run 1, base-tip (verdict of record) on `3a5785f0`.** It aborted at the gate preflight with `FAIL env: missing toolchain: python … postgres`. A fresh worktree has no `.toolchain/` (gitignored). Fix: symlink the caller's `.toolchain` (plan-v2's GX-05 note says the same).
- **Run 2, base-tip on `3a5785f0`.** Script tests failed: `generate.test.sh` (env: `apps/web/scripts/intents-doc.ts`, node ESM loader, in the throwaway worktree; it passes locally) and `train-role.test.sh` (3.1, mine). The other 6 stages passed; total 149.9 s.
- **Run 3, own checkout on `3a5785f0` (report-only).** Script tests failed: only `generate.test.sh` (the same env failure).
- **Final runs on the final head:** see the RETRO comment and the MERGE-READY comment.

## 5. Lessons (change → owner)
1. **`config.get` under a foreign config module.** It should resolve the registry of the module that calls it, or the gate should not import tool-root Python into the code under test. Until then, the rule is: "a module that adds a registry key reads it by its checkout root". Owner: engine-config / GX-05 (pinned gate).
2. **Literal check before commit.** Run the literal census (`scripts/structure-check` or a `local-checks` entry) in the *pre-commit* path, because the push guard pushes at commit time. Owner: push-guard / local-checks.
3. **Base-tip worktree toolchain.** A base-tip worktree needs the caller's `.toolchain` (symlink or PATH). Put it in the D-A3 protocol and in GX-05's tool-root setup. Owner: GX-05.
4. **`generate.test.sh` in a throwaway worktree.** It fails with a node loader error there and passes in the checkout; that belongs in the known-env list. Owner: GX-ENV.
5. **Restate the commit budget.** A scope absorption should restate the commit budget. Owner: coordinator brief template.
6. **Test in three modes.** Tests of anything that reads the config store should run plain, with `OU_CONFIG_STORE=file`, and under base-tip tooling. A helper target in `scripts/run test` would make that one command. Owner: engine-config.
