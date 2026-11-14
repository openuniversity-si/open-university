# U4 factory-domain: audit

Read-only findings, base `bb8fb9b4` (mod/roadmap-integration).

- **Physical form.** Units stay logical (S1, P-03): the files keep `apps/web/src/factory/domain/**`, the manifest paths are unchanged and no
  path moves, so D-029 leaves no old path behind. The `@ou/factory-domain/*` alias already exists and is generated.
- **Consumers.** Three files outside the unit import it, all through the alias: `factory/server/youtube-adapter.ts`
  (`parseCurated`, `CuratedV1`, `youtubeDurationSeconds`), `factory/testing/adapter-contract.ts` and `factory/ports/source-adapter.ts` (`CuratedV1`).
- **Literals.** The no-literals check finds none and no `x-literal-sites` entry names a file of this unit; the allowlist is already zero.
- **Battery.** `scripts/unit-battery factory-domain` is green in 3.5 s (limit `battery.unit_time_limit`).
- **Size.** 764 production lines, ceiling 1500: not oversize.
