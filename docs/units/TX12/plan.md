# TX12 plan — env premises labelled env, not code

Findings F1-F10 are in [audit.md](audit.md). Lane: engine-lane only (every path below maps to engine-lane or to no
unit). Premises: P-46 (pinned gate, offline path).

## Commits (dependency graph)

```
1 audit ── 2 plan ── 3 registry bootstrap ──┬── 4 root identity premises
                                            └── 5 claude session stamp ── 6 shim guard ── 7 retro
```

| # | Delivers | Files | Targeted tests |
|---|---|---|---|
| 1 | Audit (F1-F10) | `docs/units/TX12/audit.md` | – |
| 2 | This plan | `docs/units/TX12/plan.md` | – |
| 3 | F6: `env-premises.session_id_floor/ceiling` in a new bootstrap owner, read without the store; `test_passwd_fallback` asserts no store read | `config/registry/env-premises.json` (new), `config/registry/env.json`, `config/registry/config.json`, `scripts/lib/session_identity.py`, `scripts/lib/generated/*` (scripts/generate), `scripts/tests/test_root_identity.py` | root-identity, env |
| 4 | F1-F5: `MachinePremise` prints `FAIL env: <premise>` and is not an `AssertionError`; uid 65534 interpreter/checkout probe; `sudo -n` premise; `OU_CONFIG_STORE` passed through `sudo env`; missing toolchain is a premise, not a setup run | `scripts/tests/test_root_identity.py`, `scripts/tests/root_probe.py` if needed | root-identity |
| 5 | F7, F8: per-test `OU_PREFLIGHT_STAMP`; toolchain premise before setup | `scripts/lib/credentials.py`, `scripts/tests/test_claude_session.py` | claude-session, cloud |
| 6 | F9: `OU_SHIM_GUARD` honored under `$TMPDIR` as well as `/tmp`; test premise names an ignored guard | `scripts/cloud/env.sh`, `scripts/tests/test_claude_session.py` | claude-session, env, cloud |
| 7 | Retro | `docs/units/TX12/retro.md` | the single final pinned gate |

## Premises (blast radius)

- **CRITICAL** — `config.bootstrap_owners` gaining `env-premises` changes `config.get` for those names only (registry
  value, never the store). Radius: the two id-range keys; scripts/config then refuses to change them (edit the file).
- `OU_PREFLIGHT_STAMP` unset keeps `<toolchain>/preflight.stamp` exactly: radius none outside tests.
- The `$TMPDIR` guard is still a temp directory only (the rule's intent: a tripwire never comes from the checkout).
- P-46: the final gate is the pinned offline gate (`OU_CONFIG_STORE=file`), recorded in the PR.

## Final gate

`OU_CONFIG_STORE=file bash scripts/cloud/setup.sh`, then
`(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr 752)`, once.
