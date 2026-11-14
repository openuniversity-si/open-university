# GX-FIX-registry audit

- `scripts/lib/hermetic/sitecustomize.py` put the tooling's `scripts/lib` first on `sys.path` and imported `hermetic`, which imports `config`; both stayed in `sys.modules`, so code under test got the tooling's `config.py` (`_ROOT` = tool root) and read the base registry.
- Effect: a PR adding a registry key read by its own tests fails with `config: <key> is not a registered parameter` under the pinned gate (GX-05).
- Pin lives in module state (`config._pinned`), not in `os.environ`, so a fresh head `config` loses it.
- Guard gap: `scripts/tests/test_hermetic.py` only ran with the checkout's own tooling.
