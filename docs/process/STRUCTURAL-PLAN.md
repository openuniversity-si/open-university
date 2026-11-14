# Structural plan: the 20 root causes of the Brazil batch test

**Historical (Open University era).** Many scripts and contexts this plan names have since left the repository with
the product (D-105, D-111) or later retirements (`env-update` with VAZÃO F13, the assets inventory with D-292): read it
as the record of the plan, not as a map of today's tree.

Status: Approved by Daniel 2026-10-22 (D-013), with Q1–Q6 answered (D-014 … D-019). PRs run in parallel lanes (D-021, amends D-020). Source: the Brazil batch test
diagnosis (`/workspace/torre/catalogo/brasil/SHIP-DIAGNOSTICO.md`, 11 class findings) and the root-cause analysis
approved by Daniel (4 lines × 5 instances). Base: `origin/main` `ead274e` (PR #241 already made areas data).

Design: [CONTRACT.md](../domain/CONTRACT.md) · [DECISIONS.md](../domain/DECISIONS.md) ·
[STRUCTURE.md](STRUCTURE.md) · FACTORY.md (archived with Open University at `567176bb`, D-110) · first capability
[CAP-001](../capabilities/CAP-001-publish-any-batch.md).

Order: structure first (contract, rites, schema, rules core, hierarchy), then the batch built on it, then the factory,
then cost. Each PR is small (D-008), runs the normal tail (`ship-tail`), is executed by one Claude Code session (D-007;
after the session limit, Cursor cloud agents continue this queue, D-021) and carries the fit-review trailer
(STRUCTURE.md B5). **Parallel lanes (D-021, amends D-020):** independent PRs run at the same time; a PR merges only
after its "Depends on" predecessors are merged and their production deploys are verified. Migrations continue after `0023`.

## The 20 instances

| Line | 1st | 2nd | 3rd | 4th | 5th |
|---|---|---|---|---|---|
| **A** Publication in steps | A1 bundle incomplete; CLI fills gaps around the commit | A2 operation grew by patches | A3 unit of publication never defined | A4 deliveries asked, not capabilities | A5 execution without design |
| **B** Rules in three copies | B1 validator, CLI and server reimplement rules | B2 rules live in routes/scripts | B3 catalog contract never written | B4 each agent starts from scratch | B5 no architecture owner |
| **C** Media with fixed owner | C1 media only for course/lesson/subarea | C2 model built screen by screen | C3 hierarchy is not a concept | C4 decisions stay in chat | C5 no path decision → model |
| **D** Factory without format/env | D1 one converter per source; CLI from a stray copy | D2 ingestion is throwaway scripts | D3 factory outside the architecture | D4 factory is not a product | D5 only what is live is measured |

Extra class items folded in (diagnosis numbering): X1 covers attached after commit (#1) · X2 no server dry run (#2) ·
X3 id 80 vs 64, invented 2020 (#3) · X4 prerequisites outside the bundle, institutions as `person` (#4) · X5 university
row chicken-and-egg, one release per row (#5) · X6 area has no shared cover (#6; the hardcoded area list is already
solved by #241) · X7 curation ≠ bundle input, translated titles, scheduled videos (#7) · X8 texts approved by their
generator (#8) · X9 CLI friction: Node 22, `/tmp/torre-env.sh`, stray install, `--to`+`--target`, envelopes (#9) ·
X10 slow reads: course list 18.5 s, redirect list 11.7 s (#10) · X11 release ~23 s fixed (#11) · X12 shellcheck
findings breaking `gate-quiet` · X13 subarea cover state = 111 calls / 44 s.

## PRs, in order

| # | PR | Closes | Proof (tests) | Depends on |
|---|---|---|---|---|
| **S00** | `docs/structure-contract` — this branch: CONTRACT, DECISIONS, STRUCTURE, FACTORY, this plan, CAP-001; `AGENTS.md` "Read first" block. | A3 (written), A4·A5·B5·C5·D5 (rites written), B4 (feed), C4, D3 (declared) | Docs only; relative links resolve (checked by hand in fit review; `structure-check` from S00b). | — |
| **S00b** | `scripts/structure-check` + `scripts/idea-to-prod`; `ship-verify` requires `Fit-Review:`; PR trailers `Capability:`/`Instances:`/`Claude-Session:`. | A4, A5, B5, C4, C5, D5 (rites made executable), D-006/007/008 checks | `scripts/tests/structure-check.test.sh`: rejects a capability without `requested:`, a visual one without `figma:`, a `D-NNN` without proof or pending PR, a structural PR without fit review; `idea-to-prod` fixture prints the expected line. | S00 |
| **S01** | `cli/run-from-repo` — wrapper uses `.toolchain/bin/node` (Node 22 from `toolchain.json`); remove the `/tmp/torre-env.sh` hint; `install` shim records the checkout and refuses a dirty or detached one with a clear message; `--to` implies `--target`; one JSON envelope `{ok,data}` for every command. | D1 (env), X9 | `scripts/tests/tower-catalog-wrapper.test.sh` (node from toolchain, stale-checkout refusal); `tower-catalog.test.ts` › every `--json` command has the envelope; `--to prod` alone works. | — |
| **S02** | `gate/shellcheck-clean` — fix the pre-existing shellcheck findings so `gate-quiet` is green; no disables without a reason line. | X12 | `gate-quiet` passes; shellcheck stage in nightly has 0 findings. | — |
| **S03** | `catalog/one-schema` — `src/catalog/domain/schema/` (zod) is the single source of ids, slugs, labels, limits and defaults; `validateCourseBundle` and `contracts.ts` derive from it; `edition.year` is integer or `null`; `docs/catalog/schema.md` generated with `schema:check` in the gate. Adds the D-003 progress test. | B1 (shape), B3, X3 | `schema.test.ts` › a 65-char id fails in bundle and route alike; a missing year stays `null`; `schema:check` fails on a stale doc; progress for one video in two courses stays separate. | S00 |
| **S04** | `catalog/rules-core` — `src/catalog/domain/rules/` pure functions over a snapshot slice (`CatalogRefsPort` loads refs in one round trip); rule registry with stable ids; `courses.ts`, `home.ts`, `bundles.ts`, `bundle-apply.ts`, `ship-batch.ts` call the core; checker rules `L6.rules-in-core` and `L6.single-rule`. | B1 (stateful), B2, B4 (gate rejects duplication) | `rules.test.ts` per rule id (in-memory refs); `check-architecture.test.ts` fixtures: a rule message in `server/` fails, a duplicated id fails; existing int tests unchanged. | S03 |
| **S05a** | `media/any-owner` — migration **0024_catalog_media**: one table `catalog_media(owner_kind, owner_id, kind, variant, media_sha256, version, is_active, …)` with `owner_kind IN ('institution','area','subarea','course','lesson')`; backfill from the five legacy places; media adapter reads and writes it; legacy tables frozen by a write-refusing trigger. | C1 | `catalog-media.int.test.ts`: backfill row counts equal; an `area:` attach works; a write to `course_assets` is refused; `gate-db` idempotent rerun. | S04 |
| **S05b** | `catalog/cover-resolver` — `cover-resolve.ts` (own → nearest taxonomy ancestor when inheriting → none), used by compile, projections, pages, OG, doctor; `coverProvisional` allowed with an area and no subarea; checker rule `L6.single-cover-resolver`. | C2, X6 | `cover-resolve.test.ts` (table over every node kind; never resolves from a descendant: property test over random trees); checker fixture; current schema compile is deterministic (legacy restore proof retired by D-023). | S05a |
| **S06** | `catalog/hierarchy` — migration **0025_institution_hierarchy**: `authors.kind` required (no default, backfilled), `home_rows.institution_id` required and unique for curated rows (D-016, 1:1), published course requires an area and the "More courses" rail and `UNCLASSIFIED_AREA` are deleted (D-017), deferred constraint trigger `catalog_institution_cover` (visible institution/row with a published course needs its own active cover); `hierarchy.ts` is the only walker. | C3, X4 (kind), X5 (row ↔ institution) | `hierarchy.int.test.ts`: commit fails without institution cover, passes when cover and row arrive in the same transaction; insert without `kind` fails; second row for one institution fails; publishing without an area fails and no "More courses" rail renders; parent/ancestor table test. | S05b |
| **S07** | `catalog/batch-v2` — `CatalogBatchV2` type + schema (from S03) + pure planner `planBatch(batch, refs) → ordered ops + failures`; converter from v1 bundles directory. | A1 (format), A2 (one operation, order in core), X4 | `batch-plan.test.ts`: new institution + row + course with own covers plans in one order; conflict vs no-op on existing refs; every failure listed (G-5 in memory). | S06 |
| **S08** | `catalog/apply-batch` — `POST /batches/apply` (`dryRun` runs the whole transaction and rolls back), covers attached by sha inside the transaction before rules, refs upserted additively, Home rows with cover and OG in the same single release; `PUT /home` gains the same `dryRun`. Migration **0026_ship_batch_format** (additive `format`). | A1, A3 (guarantee tests), X1, X2, X4, X5 | `batch-apply.int.test.ts` › G-1 … G-5 (see CONTRACT §5); Brazil-shaped fixture (4 institutions, 80 own-cover courses) passes dry run and write with equal reports. | S07 |
| **S09** | `cli/ship-is-apply` — `tower-catalog ship <dir|batch>` sends only `POST /batches/apply`; deletes `runBulk`'s deferred attach, the per-course `--batch` path and per-row `home cover` releases; `--dry-run` prints the server report and exits ≠ 0 on any failure. | A2 (loose steps deleted), X1, X2, X5 | `ship.int.test.ts` › the request log of a ship is `media:/check`, `media:/objects`, `/batches/apply` only; dry run exit code and deterministic output (same input → same bytes). Removed commands fail with a pointer. | S08 |
| **S10** | `admin/fast-reads` — course and redirect lists from projections with keyset paging; `media list --owners` and `subarea list --covers` in one call. | X9 (envelope rest), X10, X13 | `read-latency.perf.int.test.ts` budgets on a 10k-course fixture (course list < 1 s, redirects < 1 s); one call returns every subarea's cover state. | S05a |
| **S11** | `catalog/incremental-release` — release cut proportional to changed courses (reuse `incremental-compile.ts`, stop rebuilding untouched projections). | X11, D4 (enabler) | `factory-bench` `releaseMs` for 1 course ≤ 2 s and for 1,000 within target; current release bytes unchanged. | S08 |
| **S12** | `factory/context` — `src/factory/` context: `curated/v1` schema, the one converter `curatedToBatch`, `scripts/tower-factory`, checker rule `L6.factory-api-only` (factory never imports `platform/db`); architecture map lists the two halves. | D1 (format, one converter), D2, D3, X7 (format) | `curated.test.ts` (translated titles, duration 0, over-long field each fail by name); `convert.test.ts` golden Brazil-shaped fixture → batch v2 that S07's planner accepts; checker fixture. | S07 |
| **S13** | `factory/youtube-adapter` — `SourceAdapter` + YouTube adapter (YouTube Data API v3 only, D-018, no oEmbed; original titles; scheduled videos skipped and counted). | D2, X7 | `adapter-contract.ts` over recorded fixtures (no network): original title kept, scheduled video skipped, 50-per-call batching asserted, no oEmbed request. | S12 |
| **S14** | `factory/texts-and-review` — one text generator (language, noun) writing `approved: false`; separate `tower-factory review` stamps approval with its own actor; placeholder titles flagged; approval only by the separate automatic reviewer (D-019). | D2, X8 | `texts.test.ts`: generator never approves; schema rejects generator-actor approval; "Aula de dd/mm/aaaa" flagged. | S12 |
| **S15** | `factory/bench-and-targets` — `scripts/factory-bench` (synthetic 1,000 courses: dry run + write on local PG) as a gate-noite stage; targets in FACTORY.md; new-institution runbook timed through `idea-to-prod`. | D4, G-6 | Bench report ≤ 60 s write / ≤ 30 s dry run (warning above, per ADR-34 style); report lists phases. | S11, S13 |
| **S16** | `media/retire-legacy` — migration **0027_retire_legacy_media** (D-029): drop the legacy asset tables and cover columns. No calendar wait. Zero legacy readers, proved by the doctor and by checker rule `L3.no-retired-paths`. | C1 (finished: no second model left) | `gate-db` forward + idempotent; doctor shows no legacy reader; checker rule `L3.no-retired-paths` lists them. | S05a |
| **S17a** | `gate/commit-check` — D-025: `scripts/commit-check` and a gate-dev "commit check" stage refuse a PR with no D-022 commit plan (3–8 items), with a fix-up commit, with several commits in one push, or changing the gate without citing an approved D-NNN; `structure-check --pr-body` checks the plan too; reverts 858d465 (the in-gate retry of the Next security reminder; #255 was the fix). Root cause: incident 2026-10-22 14:37, S06 stopped 14 min. | process (D-022, D-025) | `scripts/tests/test_commit_check.py`: one fixture per refusal and a clean PR; `test_structure.py` plan check. | S06 |
| **S17** | `structure/asset-inventory` — D-026: `docs/structure/assets.json` (+ ASSETS.md) inventories every test, fixture, script, structural doc and frozen legacy table with what it protects and its retirement event; `structure-check` fails on a missing entry or a happened retirement; migrations/transitions declare their end criterion; one sweep deletes leftovers (retired `scripts/ship`, dead `media-prepare.ts`, superseded audits, phase reports, `PROGRESSO.md`). Root cause: incident 2026-10-22 14:37. | process (D-026) | `test_structure.py` › D-026 fixtures for both failures; the repository passes its own check. | S17a |
| **S18** | `env/as-code` — D-027: `toolchain.json` becomes the environment manifest (toolchain + critical dependencies + update policy); `scripts/env-check` (versions, advisories, build smoke) runs first in `idea-to-prod`; the gate tags a red stage `code`/`env`/`contract` with its action in AGENTS.md; `scripts/env-update` applies allowed patch/security updates and runs the gate. (Its commit-discipline part became S17a.) Root cause: incident 2026-10-22 14:37. | process (D-027) | `test_env.py`, `test_gate_classify.py` | S17 |

Parallel lanes (D-021, amends D-020 for this effort): PRs whose "Depends on" prerequisites are in production run in parallel; a dependent PR may be prepared stacked on its predecessor's branch but merges only after the predecessor is merged and its production deploy is verified. Target: S02–S15 in production by 14:00 America/Sao_Paulo on 2026-10-22. Because the Claude account hit its session limit at about 12:25, Daniel authorized at 12:53 Cursor cloud agents running Grok 4.7 High Fast to continue the queue (an exception to D-007 for this effort).

## Rites (no PR besides S00/S00b)

| Rite | Instance | Where |
|---|---|---|
| Capability first | A4 | STRUCTURE.md A4; CAP-001 is the first one |
| Design before PR | A5 | STRUCTURE.md A5; `structure-check` |
| Contract fed to every agent | B4 | AGENTS.md "Read first"; launch prompts |
| Structure owner + fit review | B5 | STRUCTURE.md B5; `ship-verify` trailer check |
| Decision → register → test → code | C5 | STRUCTURE.md C5; DECISIONS.md |
| Idea-to-production metric | D5 | STRUCTURE.md D5; `idea-to-prod` weekly |

## Traceability

| Instance | Solved by | Proof |
|---|---|---|
| A1 | S07 + S08 | G-4 (one batch with new institution, row, own covers), G-1 |
| A2 | S07 (planner) + S09 (loose steps deleted) | `batch-plan.test.ts`; `ship.int.test.ts` request log |
| A3 | S00 (CONTRACT §5) + S08 | G-1 … G-5 tests in `batch-apply.int.test.ts` |
| A4 | Rite A4 + S00b | CAP files; `structure-check` |
| A5 | Rite A5 + S00b | `structure-check` rejects a structural PR without an approved CAP |
| B1 | S03 (shape) + S04 (stateful rules) | `schema.test.ts`, `rules.test.ts` |
| B2 | S04 | `L6.rules-in-core` checker fixture |
| B3 | S03 | `schema:check` in the gate; one 65-char id test across bundle and route |
| B4 | S00 (AGENTS.md) + S04 (`L6.single-rule`) | checker fixture for a duplicated rule id |
| B5 | Rite B5 + S00b | `ship-verify` refuses a PR without `Fit-Review:` |
| C1 | S05a + S16 | `catalog-media.int.test.ts`; legacy dropped |
| C2 | S05b | `cover-resolve.test.ts`; `L6.single-cover-resolver` |
| C3 | S06 | `hierarchy.int.test.ts` (deferred institution-cover trigger, required `kind`) |
| C4 | S00 (DECISIONS.md) + S00b | `structure-check`: every D-NNN has a proof or a pending PR |
| C5 | Rite C5 + S00b | same-day entry; `test pending` > 7 days in the weekly report |
| D1 | S01 (env) + S12 (format, one converter) | wrapper test; `curated.test.ts`, `convert.test.ts` |
| D2 | S12 + S13 + S14 | adapter contract test; texts test |
| D3 | S00 (FACTORY.md) + S12 | `L6.factory-api-only`; context in the checker |
| D4 | S15 (+ S11) | `factory-bench` in gate-noite |
| D5 | Rite D5 + S00b | `idea-to-prod` fixture test; weekly report |

**All 20 covered: yes.** Extra items: X1 S08/S09 · X2 S08/S09 · X3 S03 · X4 S06/S07/S08 · X5 S06/S08/S09 · X6 S05b
(area list: done in #241) · X7 S12/S13 · X8 S14 · X9 S01/S10 · X10 S10 · X11 S11 · X12 S02 · X13 S10.

## Decisions (formerly open questions)

Daniel approved the design, CONTRACT.md as chapter 1 and the order S00 → S16 on 2026-10-22 (D-013), and answered Q1–Q6
the same day ([DECISIONS.md](../domain/DECISIONS.md#resolved-questions)): a course never borrows its institution's
cover (D-014), area cover sets come from Figma starting with Education (D-015), a university row is 1:1 with its
institution (D-016), every published course has an area and "More courses" goes (D-017, implemented in S06), lesson
titles come from the YouTube Data API (D-018), and generated texts are approved by a separate automatic reviewer
(D-019). PRs ran strictly serially (D-020) until D-021 allowed parallel lanes for S02–S15.
