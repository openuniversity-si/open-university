# Retiring a product

How a product leaves this repository (OU-DECOUPLE, D-105, D-110, D-112, D-113). Open University followed it on
30/10/2026. Each step is its own PR, gated and merged through the train. The order is set by the pinned gate (P-46): a
PR is judged by its base's tooling, so the base must be ready for each step before the PR that takes it.

1. **Decide.** Record the owner's decision as a D-NNN: what leaves, what stays, and what happens to production.
2. **No path without an area.** The area map is total (D-106). Without it, a removal's unmapped paths would plan the
   full battery.
3. **The gate stops running the product.** Its stages leave the area map. Its areas keep their paths with no group,
   so every path keeps an area (D-108). A stage name stays listed only while an older loader still needs it (D-109).
   Port into the engine every engine rule the product's own tests held. Prove the engine stages on a worktree with the
   product deleted, judged by the new base's own `scripts/gate-local --report-only`.
4. **Archive.** Record the last commit that holds the whole product, and tag it when the session can push tags
   (D-110). A standalone repository can be cut from it later with `git filter-repo`.
5. **The base learns to judge the retirement (D-112).**
   - A unit whose manifest the change deletes decides no lane, and its deleted files are no visual edit.
   - Retire every registry key the product alone reads: the key leaves with the code that read it, in one
     revision, and schema compat refuses it while the tree still names it (D-289); a key with a live reader
     is marked deprecated first.
6. **Remove.** Delete in one PR the product, its units, its tooling, its tests, its registry keys and its docs, with
   the engine code and tests that read them. List every removed test with the code it tested. Engine coverage of
   behaviour that stays never drops.
7. **The engine names no product (D-113).**
   - Make every remaining acting reference generic, or delete it.
   - Add the root to `structure.retired_product_roots`; the structure check holds it at zero from then on.
   - Records (`structure.record_globs`) keep the past.
8. **Production goes offline last.** Use the least destructive reversible action, announced on the PR first. Data
   stores are kept.
