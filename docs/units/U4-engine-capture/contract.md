# engine-capture contract 1.0.0 (U4)

The unit's published surface is what other units import today (computed from the import graph):

| Export | File | Used by |
|---|---|---|
| `capturePage`, `installCaptureRoutes`, `readFreshHealth` | `scripts/lib/capture-page.mjs` | `scripts/tests/production-capture.test.mjs` (engine-test-support) |
| `chromiumArgs` | `scripts/lib/chromium-args.mjs` | the same test; the e2e launchers |
| `rasterParity` | `scripts/lib/raster-parity.mjs` | the same test |
| `auditInherited` | `scripts/lib/prune-inherited-audit.mjs` | `scripts/tests/prune-inherited.test.mjs` |
| `DirectImageNormalizer` | `scripts/lib/direct_image_normalize.py` | `scripts/lib/ship_verify.py`, `scripts/tests/delivery_test.py` (engine-production) |
| `scripts/cloud-webkit start\|stop` | `scripts/cloud-webkit` | gate e2e launchers (entry script, path unchanged) |

Everything else (`capture-config.mjs`, the CLI bodies of `direct-image-capture`, `media-parity`, `production-capture`) is internal. A breaking change goes expand->contract (P-07, D-029) and bumps the version here.

## Why the version is not in `units/engine-capture/unit.json`
`contracts/units/unit.v1.json` takes `contract: {entry, version}`, but the unit battery's `contract` step resolves `entry` under the unit's `@ou` address home, and no `scripts/` unit has an address (UNITS.md). A manifest `contract` would turn `scripts/unit-battery engine-capture` red. Recorded for the owners of `engine-battery` / `engine-units`: when scripts units get a home, add `{"entry": "scripts/lib/capture-page.mjs", "version": "1.0.0"}` to the manifest.
