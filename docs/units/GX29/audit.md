# GX-29 audit — hermetic network, DB residue, covers trace

Base `ba98e586` (mod/roadmap-integration, GX-FIX-modules #712 merged). Read-only findings.

## Cited sources checked
- `scripts/lib/hermetic.py`, `scripts/lib/hermetic/sitecustomize.py`, `scripts/lib/test_db.py`, `scripts/lib/gate-fixed.sh`, `scripts/lib/gate_script_tests.py`, `scripts/cloud/setup.sh`, `scripts/cloud/fonts.py`: all exist.
- `config/registry/cloud.json` **already exists** on the base (owner `cloud`), so the brief's "new cloud.json" is wrong: `cloud.offline_seed_paths` is added to the existing file. `config/registry/gate-trace.json` does not exist and is created.
- Covers are per-test sidecars (`scripts/tests/covers/<test>.json`, GX-08); `scripts/lib/gate-script-tests.json` is gone.
- Branch: the harness designates `claude/gx29-hermetic-network-t66m63`; the brief says `mod/gx29`. One branch only: the designated one (precedent: GX-19 merged from a `claude/…` branch).

## Findings
1. **Network.** `hermetic.py` denies sockets only inside Python processes that load `scripts/lib/hermetic/` (script tests). The gate's shell, Node (pnpm, vitest, media:cache, next) and browsers are not covered. `gate-local:449` runs `playwright install chromium`, which downloads unless `PLAYWRIGHT_BROWSERS_PATH` already holds the browser; pnpm needs its store; `fonts.py` pip-installs `fonttools[woff]`; `media:cache` already has `--offline` and `TOWER_MEDIA_SEED_DIRS` (gate-fixed.sh exports the cache dir) but `gate_media_prefetch` never passes the flag.
2. **DB residue.** `postgres.py ensure` creates the bootstrap database `cloud.postgres_database` (`tower_test_f02`) and any test that boots the toolchain re-creates it; nothing drops it (GA2 Q9: 2 `tower_test_*` databases after two gates, no growth between runs). `test_db.py` can only create/destroy names it generated (`validate`). Local cluster now holds `tower_test_f02` and the checkout's own database.
3. **Covers trace.** `gate_script_tests.select` maps a diff to tests by declared `covers` globs; nothing checks that a test reads only what it declares. Under-declared covers mean a change to an undeclared file does not select the test (G-14).
4. Known base failures (not scope): claude-session, root-identity, config script tests (env); KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.
