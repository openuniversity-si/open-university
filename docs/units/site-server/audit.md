# site-server audit (U4)

Read-only findings, base `mod/roadmap-integration` c37cb2d4.

- Unit: 15 files under `apps/web/src/site/{application,ports,server,testing}/` (4 application use cases, 1 port, 4 server modules plus a test, 6 testing files), 357 lines, far under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03 `validated`). The files keep their paths; `@ou/site-server/*` is generated into `apps/web/tsconfig.json`. Nothing moves, so there is nothing to delete (D-029). The brief asked for `units/site-server/`; `units/<id>/` holds only the manifest.
- Importers (not this unit's files, not edited): 19 imports of `@ou/site-server/application/*` from `app/` and `ui/` (`site-data` 15, `indexing` 2, `build-info` 1, `csp-report` 1). No importer reaches `server/`, `ports/` or `testing/`; the remaining `site/server` hits are architecture-check test fixtures.
- Imported surface (the contract): `application/site-data` (`siteData`, `LEGAL_EMAIL`), `application/indexing` (`siteIndexingFacts`), `application/build-info` (`buildInfo`), `application/csp-report` (`answerCspReport`).
- Literals: no tunable in the 11 production lines that carry logic. The limit (`LIMITS.cspReportBytes`) and status (`HTTP_STATUS.noContent`) come from the kernel; `CSP_REPORT_ONLY` is a log event name. `config_check` has no `x-literal-sites` entry for the unit, so the allowlist is already zero.
- UI text: none. The unit holds no user-facing strings (institutional copy is site data, L1.no-site-pages); `site-text` owns the `text.*` entries.
- Battery: `scripts/unit-battery site-server` green in 4.1 s (types 16 files, unit 4 files) against `battery.unit_time_limit`. Tests are hermetic: in-memory site, no network.
