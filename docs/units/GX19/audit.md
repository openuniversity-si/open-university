# GX-19 audit (read-only, base ffcf6397)

Branch `claude/gx19-stage-timeouts-eviction-dpnzge` (the session designates it; the brief's `mod/gx19` is not used: one branch, one PR).

## Cited sources, verified on the base
- `scripts/lib/gate-runner.sh` `step` runs `(cd "$dir" && "$@") >"$log"` with no time limit (F-05). Stages are commands **and shell functions** (`run_script_tests`, `secret_tree`, `secret_history`), so `timeout(1)` cannot wrap them; a watchdog is needed.
- `scripts/lib/gate-hooks/exit.sh` is the GX-38 no-op `gate_hook_exit`, called first in `finish()` (`scripts/gate-local:187`). `tool_root`, `record_dir`, `cache` and `py` are set by then.
- Reports live at `$record_dir/reports/<sha>/<mode>-<timestamp>` (`gate-local:116,261`) and are never removed (F-08).
- Build cache lives at `$cache/<target>-<64 hex>` (`gate-build.py` `cached_build`); `rmtree(entry)` then `rename` at the end of a miss is not atomic: a concurrent reader can hit a half-removed entry.
- `gate_classify.py` classes a stage by log content; `FAIL env: ` is an env pattern, but a code pattern in a partial log wins, so a timeout needs its own path to be `env` every time.
- Registry: an `object` parameter must be `x-text` (meta-schema), so the stage map is an array of `{stage, timeout_s}` with a `*` entry (like `generate.targets`).
- Pre-claimed by GX-38 in `units/engine-gate-run/unit.json`: `config/registry/gate-gc.json`, `scripts/lib/gate_gc.py`, `scripts/tests/test_gate_gc.py`. No unit or CODEOWNERS edit is needed.
- `scripts/tests/gate-local.test.sh` asserts every hook body is `:`; the exit hook stops being one, so that loop narrows (and a check for the exit hook is added).

## Not in scope / expected
Known base env failures (claude-session, root-identity, config RegistryMemo, uid-65534) are GX-ENV's.
