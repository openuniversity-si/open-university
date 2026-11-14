# S2 audit: supply chain, dependency allowlist, lockfile integrity, key scopes (D-069 item 13)

Read-only findings on base a2c09043 (mod/roadmap-integration). The earlier branch is not reused.

## What exists
- `scripts/lib/vendor-map.json` (D-062): the 27 direct packages of `apps/web/package.json` plus `retired`. Read by `scripts/lib/architecture/handlers.mjs` (`L3.dependency-declared` and friends) through `packages` and `retired` only, so a new top-level key does not disturb it.
- `scripts/lib/toolchain_check.py` (T1, D-069 item 12): a `structure.py` module (`toolchain_check.check(root)`), reads `toolchain.lockfile_packages` (`apps/web`), parses importers and overrides of `pnpm-lock.yaml`. It does not read the `packages:` section.
- `scripts/lib/production_guard.py` (D-054, item 13): production entrypoints refused in cloud sessions. It holds no key scopes.
- `apps/web/pnpm-lock.yaml` (lockfile v9): about 640 `packages:` entries, each `resolution: {integrity: ...}`; none carries a `tarball:`, so all resolve from the registry pnpm uses by default. `apps/web/.npmrc` sets no `registry=`.
- Config guard (`config.guard_name_*`): keys holding secret names must hold only names matching `^[A-Z][A-Z0-9_]*$`; token-shaped values are refused.
- Secrets in use (AGENTS.md): `GH_TOKEN`/`GITHUB_TOKEN`, `NEON_API_KEY`, `VERCEL_TOKEN`, `FIGMA_TOKEN`; forbidden on cloud agents: `VERCEL_AUTOMATION_BYPASS_SECRET`, R2 keys, `AUTH_*`/`OU_GOOGLE_*`, Mux, blob tokens.
- No `supply-chain` registry owner and no lockfile package allowlist exist; the secret scan (gitleaks, `commit-check`) is separate and stays untouched.

## Gaps S2 closes
1. A transitive package is checked by nothing: any package can enter the lockfile.
2. Integrity hash presence and the resolving registry are unchecked.
3. No registry entry says which secret names each agent role may hold.

## Constraints
`package.json` and `pnpm-lock.yaml` are not changed. Gate files change under D-025/D-068/D-069 item 13. No literals: every value in `config/registry/supply-chain.json`. New module is owned by `engine-env` next to `toolchain_check.py`.
