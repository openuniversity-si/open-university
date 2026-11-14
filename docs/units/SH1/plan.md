# SH-1 plan

Critical path: 1 → 2 → 3 → 4 (≈ 60 min). Edges are real (4 needs the module, the keys and the contract). Item 5 (contract/EVENTS) only collides on `scripts/generate`, so it runs inside commit 3 with the registry keys.

1. audit skeleton (done).
2. audit.md + plan.md.
3. Registry keys `train.shard_key`, `train.shard_shadow` + event contract `train.batch.shards.v1.json` + EVENTS.md row + `scripts/generate` + unit claim.
4. `scripts/lib/train_shard.py`: pure `key()`, `shards()`, `collisions()` + `test_train_shard.py` (single unit; two units with overlapping dependents; unclaimed `docs/process/EVENTS.md`; generated `CODEOWNERS` and `apps/web/tsconfig.paths.json` not unclaimed).
5. `train.py` single call in `start_batch` + `unit.json` claim + CODEOWNERS regen + integration test (emits once; nothing when `train.shard_shadow` false).
6. retro.

Premises: P-43, P-46. CRITICAL: none (no production, money or source of truth). Premise "tsconfig.json is generated" is false on base (see audit); the generated set is read from `generate.targets`.
Gate: one pinned `scripts/gate-dev --pr 766` at the end. Known defects expected: KD ids in the brief.
