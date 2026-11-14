# U3b admin: census before and after the rewrite

Units `admin-domain` and `admin-server`, same machine (4 vCPU cloud), `scripts/unit-battery <id> --json`.

| unit | step | before: files, result, time | after: files, result, time | output |
|---|---|---|---|---|
| admin-domain | types (tsc per unit) | 9, ok, 17.8 s | 9, ok, 15.1 s | empty (no diagnostics) |
| admin-domain | unit-tests | 3, ok, 9.7 s | 3, ok, 7.0 s | empty |
| admin-server | types (tsc per unit) | 23, ok, 18.3 s | 23, ok, 11.9 s | empty (no diagnostics) |
| admin-server | unit-tests | 6, ok, 11.5 s | 6, ok, 7.5 s | empty |

- Type-check output: empty before and after for both units.
- Test census: 9 admin test files and 44 static `it(`/`test(` call sites, the same before and after.
- Battery result: `fail` on both before and after, and only because of `over_limit`
  (`battery.unit_time_limit` = 10 s). Every step is `ok`. The budget is not loosened. The times vary between runs
  on this machine; the after-run is not slower than the before-run.
