# U3b catalog lane: census

Baseline: the untouched base `a2c09043` (a worktree). After: this PR at its last commit. Each unit is measured
with its battery (`scripts/unit-battery <id> --json`): the type-check step's output and file count, and the test
files and tests the battery selects for it, run by vitest (`--project unit`, and `--project int` with
`scripts/cloud/env.sh` sourced for the int files). Acceptance: identical before and after.

| unit | types files | types output (base / after) | unit files | unit tests (base / after) | int files | int tests (base / after) | battery (base / after) |
|---|---|---|---|---|---|---|---|
| catalog-application | 25 | empty / empty | 5 | 8 / 8 | 0 | 0 / 0 | ok / ok |
| catalog-authoring-server | 9 | empty / empty | 1 | 2 / 2 | 0 | 0 / 0 | ok / ok |
| catalog-batch | 10 | empty / empty | 5 | 21 / 21 | 0 | 0 / 0 | ok / ok |
| catalog-compile | 4 | empty / empty | 1 | 15 / 15 | 0 | 0 / 0 | ok / ok |
| catalog-hierarchy | 35 | empty / empty | 13 | 66 / 66 | 0 | 0 / 0 | ok / ok |
| catalog-release-server | 8 | empty / empty | 1 | 2 / 2 | 0 | 0 / 0 | ok / ok |
| catalog-rules | 13 | empty / empty | 4 | 29 / 29 | 0 | 0 / 0 | ok / ok |
| catalog-schema | 11 | empty / empty | 4 | 25 / 25 | 0 | 0 / 0 | ok / ok |
| catalog-server-core | 12 | empty / empty | 3 | 10 / 10 | 0 | 0 / 0 | ok / ok |
| catalog-ship-server | 10 | empty / empty | 2 | 3 / 3 | 2 | 12 / 12 | fail / fail |

Totals: 181 unit tests and 12 int tests before; 181 and 12 after. No test file was
added, removed or skipped; every file's test count is equal before and after (per-unit rows above).

## Battery results

- Nine units pass on the base and after: result `ok`, every step `ok`, under `battery.unit_time_limit`.
- `catalog-ship-server` is `fail` on the base and after, with every step `ok`: its int-tests step takes about
  12-13 s, over the 10 s limit (`over_limit: true`). This is a base defect and is not caused by the import rewrite;
  the limit is not loosened (D-069 item 14). Its unit is owned by the `catalog-lane`.

## Final head

The node-run gap (commits 6 and 7) restores 83 lane files to their base text. Their batteries are therefore the base's:
on the final head the nine units are `ok` and `catalog-ship-server` is the base's `fail` (same steps, same census,
`scripts/unit-battery` run on `784ef886`). Test counts above were measured on `3e612a2b`; they are the base's for the
restored files and unchanged for the rest.

## Gaps

Node-run closure (plan item 6): 83 lane files keep the relative imports of the base, because plain Node cannot read
tsconfig `paths`. They are listed by `git show 784ef886 --stat` and the commits b0d94303 and 784ef886. The lane's other
cross-unit imports (76 specifiers in 25 files) are `@ou/<unit>/<path>`; `scripts/units check` passes.
