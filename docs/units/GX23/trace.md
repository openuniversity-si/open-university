# GX-23 access trace (D-A16, GA2 open Q4)

What lint, typecheck, unit tests and integration tests read outside `apps/web/**`, measured once on the base.

## How

- Base `mod/roadmap-integration` eaeeb29d in a throwaway worktree (`git worktree add --detach /tmp/claude-0/gx23-trace origin/mod/roadmap-integration`), `pnpm install --frozen-lockfile --prefer-offline`, local test database from `scripts/cloud/env.sh` (`pgtools_start`). No PR, no Neon, no Vercel, no secrets. Removed after.
- Each stage's gate command (`scripts/lib/gate-fixed.sh`, unscoped, without the cache flags) under
  `strace -f -qq -e trace=openat,open,stat,lstat,newfstatat,statx,access,faccessat2,readlink,readlinkat,execve,chdir`, from `apps/web`:

| Stage | Command | rc | s |
|---|---|---|---|
| lint | `pnpm -s exec eslint . --max-warnings 0 && pnpm -s exec stylelint "**/*.css" --max-warnings 0 && pnpm -s schema:check` | 0 | 96 |
| typecheck | `pnpm -s exec next typegen && pnpm -s exec tsc --noEmit` | 0 | 25 |
| unit tests | `pnpm -s test && node scripts/site-health.ts --fixture` | 1 (base defect, below) | 124 |
| integration tests | `pnpm -s test:int` | 0 | 131 |

- A path counts when it resolves inside the worktree, outside `apps/web/` and `.git/`. "Read" = a successful open/stat of a tracked file; "probe" = a lookup of a path that does not exist (a file that would change behaviour if it appeared); a directory opened with `O_DIRECTORY` is a listing. Subprocesses are followed (`-f`); `execve` shows what they ran.
- Outside the worktree only the toolchain (`.toolchain/`, node, pnpm: covered by the toolchain pins and the tool versions already in the key), `/tmp`, `/proc`, `/usr` and system libraries are read.

## Read set outside `apps/web/**`

### lint
- Files: `docs/catalog/schema.md` (`schema:check`), `scripts/check-architecture.d.mts`, `scripts/lib/architecture/engine.d.mts`, `scripts/lib/architecture/tree.d.mts`, `scripts/tests/fixtures/architecture/check-architecture.legacy.d.mts` (type resolution of the architecture checker; the `.mts` siblings are probed).
- Probes (root and `apps/`): `package.json`, `pnpm-workspace.yaml`/`.yml`, `pnpm-workspaces.*`, `.pnpm-workspace*`, `.browserslistrc`, `browserslist`, `node_modules`.
- No directory listing outside `apps/web`, no subprocess outside the toolchain.

### typecheck
- Files: the four architecture `.d.mts` above.
- Probes (root and `apps/`): `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `bun.lockb`, `lerna.json`, the `pnpm-workspace` variants, `node_modules/@types`.

### integration tests
- Files: `config/registry/battery.json`, `budgets.json`, `tests.json`, `units.json` (vitest config and helpers read the registry).
- Probes (root and `apps/`): `package.json`, `lerna.json`, `deno.json`, `deno.jsonc`, the `pnpm-workspace` variants, `node_modules/@opentelemetry/api`.
- No `git` subprocess, no listing outside `apps/web`.

### unit tests
- Every tracked file outside `apps/web` is read: scripts 723/723, docs 557/557, contracts 183/183, units 131/131, config 47/47 (tracked/read).
- Subprocesses: `git ls-files -z` and `git ls-files -z --cached --others --exclude-standard` (15 each; the whole tree's path list), `git ls-files apps/web/src scripts`, `git ls-files .github/workflows .github/actions`, `scripts/generate context-map --stdout`, `scripts/config get architecture.*`.
- Listings: the repository root, `config/registry`, `contracts/events`, `scripts/lib`, `units` and every `units/<id>`.
- Whole-tree readers (grep for `ls-files`): `src/release/domain/countries.test.ts`, `src/site/domain/no-legacy-email.test.ts` (read every listed file), `src/site/domain/no-github-actions.test.ts`, `scripts/lib/architecture-engine.test.ts`.
- Base defect seen (not GX-23's): `src/site/domain/no-github-actions.test.ts > merge-phase decides on the local gate, not on GitHub checks` fails on the untouched base (`expected '#!/usr/bin/env bash\n# scripts/merge-…' to contain 'local gate'`); 1 failed / 1787 passed.

## What the declaration does with it

- lint, typecheck, integration tests: declared in `scripts/lib/gate-stage-inputs.json` as `apps/web/**`, `contracts/generated/typescript/**`, `units/**` (the brief's list), the probes above (`shared_inputs`), plus each stage's traced files (lint: `docs/catalog/schema.md` and the architecture checker globs; typecheck: the architecture checker globs; integration: `config/registry/**`). The exact traced paths are also listed under `traced`, so a later narrowing of the globs can never drop them from the key.
- unit tests: **not declared**, stays on `**` (GA-P10). Its read set is the whole tree, contents and path list, so any narrowing would be an under-declaration (a false hit). Narrowing it needs the whole-tree tests moved to their own stage first (lesson in retro.md).
