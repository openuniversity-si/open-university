# TX12 retro — env premises labelled env, not code

PR #752, branch `mod/tx-envlabel`, base `mod/roadmap-integration` 891b835ae (did not move during the unit).

## Brief quality

Accurate and actionable. Every cited file:line held on the base except one: the
`_ou_cloud_postgres_host[0]: unbound variable` class no longer reproduces (every `_ou_cloud_load` call in
`scripts/cloud/env.sh` already ends in `|| return 1` and prints `FAIL env:`). Two fixes needed files outside the OWN
list but inside engine-lane: `config/registry/config.json` (`config.bootstrap_owners`, unowned) and
`scripts/lib/credentials.py` (engine-github, the stamp path). No other TX unit lists either; recorded in the first
STATUS comment.

## Premises

- P-46 (pinned offline gate): held; the final gate is the pinned path.
- CRITICAL `env-premises` as a bootstrap owner: held; only the two id-range keys and the new probe timeout read the
  registry value, and scripts/config now refuses to change them (edit the file).
- `OU_PREFLIGHT_STAMP` unset keeps the shared stamp path: held (preflight and cloud suites unchanged and green).

## Failures and root-cause class

- `scripts/run test <name>` answered "no such test": it requires `-x` (`scripts/run:33`) and the `*.test.sh` files are mode 0644 in git; the gate runs them with `bash`, so the suites were run as `bash scripts/tests/<name>.test.sh`. Class: env/tooling (TX10 owns `scripts/run`; reported, not fixed here).
- First literal-census run after commit 4 refused the shrunk `600`/`-2000` counts: expected, fixed by
  `literal_census.py --write engine-test-support` (my unit's baseline only). Class: code (mine).
- Gate run 1 (head 09d4ae0b, pinned, 144.8 s), two red stages, both mine:
  - `schema compat` (class code): removing `env.session_id_*` from env.json broke expand->contract (a registry
    parameter leaves only after a revision marked it deprecated). Fix 5d4b3107: the names stay, `deprecated: true`.
    Root cause: I moved keys without reading `scripts/lib/schema_compat.py` (registry rule).
  - `script tests` (class **env**, correctly): both suites printed `FAIL env: missing toolchain` because the gate's slot
    checkout has no `.toolchain`; the base relied on the tests' own setup.sh run to install it there. Fix 2012367e:
    root identity runs setup again (timeout unchanged) and labels a failed install env; claude session's setup run
    (the code under test) is no longer refused. Root cause: the audit assumed the tests run in the main checkout.
    The new labelling did its job: the stage said env, not code.
- No test failure in any targeted suite.

## Gate runs

1. 09d4ae0b: FAILED (schema compat code, script tests env), above. A first start before it was stopped during setup,
   before any stage ran.
2. Final head: pinned gate, result in the MERGE-READY comment.

## Lessons

1. A test's machine premise must never be raised as `AssertionError`: the classifier's `CODE` pattern wins over
   `FAIL env:`. Rule: raise a non-assertion error after printing `FAIL env: <premise>` (`MachinePremise` /
   `premise_failed` in `scripts/tests/test_root_identity.py`). Owner: engine-test-support; candidate for a shared
   helper module once a unit claims one.
2. A registry value a machine needs before session state exists belongs to a bootstrap owner. Rule: new machine
   premises go in `config/registry/env-premises.json`. Owner: engine-env.
3. Tests that share `.toolchain` state need their own path override (`OU_PREFLIGHT_STAMP`). Owner: engine-github.
4. A test's premise about the toolchain must hold in the gate's slot checkout, not only in the main one: run the
   targeted suite once in a fresh `git worktree` (no `.toolchain`) before the final gate. Owner: engine-test-support
   (candidate rule for `scripts/prepush`, TX01).
5. Moving a registry key is a two-revision change (deprecate, then remove): run `scripts/schema-compat --base <base>`
   with the fast checks whenever `config/registry/**` changes. Owner: engine-config (candidate for the local checks
   registry `config/registry/local-checks.json`).
