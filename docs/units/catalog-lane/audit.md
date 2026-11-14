# U3b catalog lane: audit

Read-only evidence gathered before the first code commit (U3b, lane `catalog-lane`, D-067, D-069).

## Scope and base

- Base: `origin/mod/roadmap-integration` at `a2c09043` (includes U3a #516, U2, CO1 #576, LR1 #575).
- Lane units (`scripts/units list` by owner `catalog-lane`): catalog-application, catalog-authoring-server,
  catalog-batch, catalog-compile, catalog-hierarchy, catalog-release-server, catalog-rules, catalog-schema,
  catalog-server-core, catalog-ship-server.
- Branch: the harness designates `claude/u3b-catalog-addresses-m02diu` for this session. The brief's name
  `mod/u3b-catalog-addresses` is not used, so the work stays on the designated branch. The branch was reset to
  the current base; no old commit of PR #539 is reused.

## Evidence

- `scripts/units addresses --json` lists every unit that has an address. All ten lane units have one, and so do
  every unit they import (kernel-*, db-*, media-*, release-domain, site-domain, progress, platform-runtime,
  playback-*, testing-support, tooling-entrypoints). `none` is empty for every target of the lane.
- Cross-unit imports in lane files, planned by a read-only resolver (`scripts/lib/unit_map.py` `resolve_file`, the
  tsconfig aliases `@/*`, `@tower/playback-engine`, `@tower/media`, `@tower/catalog`, and relative paths):
  **108 files, 500 import specifiers** across 10 lane units; the targets are 30 units.
- **Gaps: 0.** Every cross-unit target is a file owned by a unit with an address and sits under that unit's home,
  so each import has an `@ou/<unit>/<path>` form that `scripts/lib/unit_addresses.py` `check()` accepts.
- Same-unit imports (`../x` inside one unit) are not touched. External packages and `vi.mock("...")` package names
  are not touched (no cross-unit path appears in a `vi.mock`).
- The rewrite is pure text substitution of the specifier. No file moves, no export is renamed, no test is added,
  removed or skipped.

## Premises checked

| Premise | Check | Result |
|---|---|---|
| P-03 (units are addressed by `@ou/<id>`, paths may change) | `scripts/units addresses` | holds for all targets of the lane |
| P-13 (one owner per file, lanes never edit the same file) | `scripts/units owner <file>` for each rewritten file | every rewritten file is owned by a lane unit |
| P-05 / P-07 (no literal lane; contract changes stay compatible) | the change touches import specifiers only; no contract, schema or config value changes | holds |
| a rewrite changes resolution | type-check and test census before and after, per unit | to be recorded in the PR body (baseline in progress) |

No premise is CRITICAL: nothing here spends money, touches production or changes the source of truth.

## Known risks

- An address names the home of a unit; a file outside a unit's home would break an import. The planner already rejects
  such targets (none occurred).
- The alias `@tower/*` entries are hand-written tsconfig keys that stay as they are; only the lane's imports stop using
  them.
- The timing-sensitive tests named in the brief (tower-catalog cover concurrency, read latency) are not changed.

## Baseline

Baseline battery per lane unit (`scripts/unit-battery <id> --json`) runs on the untouched base before the first
rewrite, recorded with the census in the PR body.
