# db-catalog-io retro (U4)

1. **Brief.** It asked to move the unit into `units/db-catalog-io/`; S1 (P-03) keeps units logical, so nothing moved and no old path needed deleting. It named branch `mod/u4-db-catalog-io`; the session's branch is `claude/u4-db-catalog-io-bs7r83`.
2. **Finding.** The only real defect was the battery: 12 to 14 s against the 10 s limit, caused by the integration test importing the admin fixture (1206 files in the type check). The unit now reads `TEST_DATABASE_URL` itself: 7.8 s. Literals were already zero.
3. **Gate.** gate-dev passed on the first run: 570 s wall on 4 vCPU (ceiling 180 s exceeded by the base, lint 248 s, integration 236 s, unit tests 202 s; none from this PR).
4. **Lessons.** (a) A unit's tests should not import a heavy shared fixture for two constants; the type-check closure is the battery's cost (owner: lane). (b) The contract slot stays empty when the entry file belongs to another unit (`db-catalog-store/index.ts`); an entry here would be a shim.
