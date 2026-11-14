# TX30 audit: tooling tmpfile load flakes at the cause

Base 891b835ae (mod/roadmap-integration). Principle T7: remove the I/O, do not lengthen the timeout.

## Brief evidence re-verified

| Claim | On this base |
|---|---|
| sync.test.ts "enforces MEDIA_BYTE_BUDGETS": 6 mkdtemp, 12 zero-buffer writes, never removed | Holds (sync.test.ts:34-44 before the change). `Buffer.alloc(MEDIA_BYTE_BUDGETS[kind])` and `+ 1`, per kind. |
| Code under test reads only `statSync().size` (covers.ts:50) | Holds, but the file moved to `@ou/tooling-catalog-cli-media/covers.ts:50`. The other `readFileSync` hits are for hero rendering, not `planCovers`. |
| "lists every problem of a folder at once" leaves a /tmp/covers-* dir | Holds (`mkdtempSync`, no cleanup), one byte per file. |
| "is stable: a second run changes nothing" leaves /tmp/snapshot-* | New finding: same class, small JSON files, never removed. |
| absolute-literals.test.ts:65-85, 14 mkdir+write | Partly stale: it already writes empty files and removes its root in `finally`. It leaves nothing; its cost is 14 mkdir+write in the shared tmpdir. |

Leftovers of one vitest run of sync.test.ts on base: 8 dirs (7 `covers-*`, 1 `snapshot-*`), 1,402,892 bytes.

## Class search

`rg "mkdtemp|tmpdir|Buffer.alloc"` over the two owned files: all hits fixed. Other tests with the same pattern are outside this unit's files and lane ownership; not touched.

## Seam

None needed. `planCovers` uses `statSync().size`, so a sparse file asserts the same sizes.
