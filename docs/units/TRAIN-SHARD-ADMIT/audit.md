# TRAIN-SHARD-ADMIT: audit (admitting a PR that is behind the tip on disjoint units)

Daniel, 29/10/2026 14:35 BRT, through A Torre: "Aprovo a decisão, lança a TRAIN-VERDICT e já planeja a admissão por
shards." 14:51: "O Gate via API não resolveria justamente o problema da base dinâmica? Com 1.000 PRs/dia a base sempre
estará desatualizada." 14:52: the two units are one program in one PR (#802), shard admission is the **core**, not a
future step. Recorded by amending D-075 (not yet merged) and by the confirmed high-radius premise P-54. First written
as planning only in #803 (closed into #802). Base: `mod/roadmap-integration` at `80839a23`; line numbers are that
head's.

## 1. The gap D-075 leaves

D-075 admits a PR only when its verdict was judged on the current tip. Every merge moves the tip, so with N lanes ready
together only the first PR lands at once; the others merge the base and ask for a new verdict, or pay the `tier2`
fallback (a batch of one). This unit plans the next step: admit a PR whose verdict is on an **older** tip `B` when
nothing that changed on the base since `B` can touch what the PR changed, as measured by the shard key.

## 2. What exists today (shadow only)

- `scripts/lib/train_shard.py` (SH-1, GX-34; design `docs/programs/gate-excellence/design-sharded-tier2.md` §4.1, §8).
  `key(manifests, files, generated)` (`l.66`) is pure: through `causes()` (`l.46-63`) every changed file maps to the
  units whose `paths` globs claim it (`units/*/unit.json`; 111 of 112 manifests declare paths), then transitively to
  every unit that `requires` one of them (`dependents()`, `l.37-43`, the reverse of `requires`); a file no unit claims
  becomes `path:<file>`; a file that is the output of an enabled committed generate target (`generated_globs()`,
  `l.31-34`) is skipped. The key is a sorted list of `unit:<id>` and `path:<file>` strings.
- `collisions()` (`l.70-80`) and `shards()` (`l.83-96`) group members by shared elements; `report()` (`l.99-104`)
  builds the payload.
- `announce()` (`l.107-122`) runs from `Train.start_batch` (`scripts/lib/train.py:207`) and emits
  `train.batch.shards` (`docs/process/EVENTS.md:44`) for every batch while `train.shard_shadow` is true
  (`config/registry/train.json:298-307`, default true). It reads the manifests **at the batch base**
  (`train_ownership.UnitOwnership.manifests`, `train_ownership.py:31`). It only measures: the verdict and the merge
  never read it, and a failure to measure is printed and skipped.
- `train.shard_key` (`train.json:286-297`) has one value, `units+dependents`; any other is an error (`check_mode`,
  `l.24-28`), never a fallback.
- What the shadow does **not** measure: the key of the base's own change since a PR's verdict, which is the question
  this unit needs answered. Today it only compares the members of one batch with each other.

## 3. The rule (D-075 as amended, P-54)

> A queued PR with head `H` and a cold, verified v4 verdict on base `B` (all of D-075's conditions except
> `base_sha == tip`) is admissible on tip `T` when `B` is an ancestor of both `H` and `T`, `T` is at most
> `train.shard_admit_max_behind` first-parent merges past `B`, neither `B..H` nor `B..T` touches a
> `train.shard_admit_never` path, and `key(files(B..H)) ∩ key(files(B..T)) = ∅` with both keys computed from the
> manifests **at `T`** and generated outputs counted as shared `path:` elements.

The merged tree is then `tree(H)` plus the changes of `B..T`: a tree **no gate judged**. That is where the rule
departs from P-43. It acts only under `train.shard_admit = on`; the default `shadow` computes the same answer, merges
nothing on it and records each would-admit, so the rate and the safety are measured first (plan §4).

Why this answers Daniel's 14:51 question. At 1,000 PRs/day the tip moves every couple of minutes; D-075's strict rule
(base = tip) admits only the first ready PR of a burst and sends every other one back for a new verdict. The gate API
makes a verdict cheap to ask for, but each re-verdict still costs a gate run. With shard admission the verdict stays
valid across every merge that did not touch the PR's units or their dependents, so a re-verdict is needed only on a
real collision.

## 4. Why it partially refutes P-43

P-43 (`docs/process/premises/gate-tier2-exact-attested-reuse.yml`, confirmed, high): tier 2 reuses a proof only when
its key matches **the exact merged tree**. D-075 / P-53 keep that literally (tested tree = merged tree). Shard admission
accepts a proof for a merged tree that differs from the tested one in paths outside the PR's key. P-43 stays true
everywhere else (batch reuse, D-075's strict mode) and is refuted only in this case, so the change needs a new
high-radius premise (P-54, confirmed by Daniel 14:51/14:52) and the amendment of D-075 (which amends D-065 (5) and
D-070 (b)). P-43 is not answered `superseded`: it stays confirmed for every other path, and P-54 names it in its
reasons. The design already named this gap: `design-sharded-tier2.md` §4.1 "Contract gap" and SH-3 in §8.

## 5. Risks and mitigations

| Risk | Why the key can miss it | Mitigation |
|---|---|---|
| **Semantic conflict across disjoint units** | An interaction no `requires` edge records: a runtime registry read, two units writing the same row shape, a shared env var, an event contract both read. The key sees declared dependencies, not behaviour. | Measure the rate in shadow first ([plan.md](plan.md) §4); tier 3 (the battery on `integration.advanced`, `gate-noite`) is the confirm run, and a red confirm attributed to an admitted PR reverts that merge (`git revert -m 1`), never a later PR. |
| **Undeclared dependencies** | A unit that imports another without `requires` is invisible to `dependents()`. | Admit only when the unit-edge check (`structure-check`, D-067) is green at `T`; count shadow false-disjoints by cause. |
| **Generated files and aggregates** | `causes()` skips generated outputs: two PRs that both regenerate `CODEOWNERS` or a registry module look disjoint while their outputs differ. | For admission, treat a generated output as a shared `path:` element (unlike the shadow); SH-2 (`train.publish_aggregates`, the train writes aggregates) removes most of them. |
| **Shared files: lockfile, registry, root config** | `pnpm-lock.yaml`, `package.json`, `config/registry/*.json`, `tsconfig`: unclaimed ones become `path:` elements (a collision, good), but a file claimed by a broad unit can hide that two unrelated units change behaviour through it. | A deny-list key `train.shard_admit_never` (lockfile, root manifests, the registry index, gate files): touching one on either side makes the PR inadmissible behind the tip. |
| **Stale dependents map** | `B..T` may change the manifests themselves (a new `requires`, a moved path), so keys from `B` would be wrong. | Compute both keys from the manifests at `T`; refuse when `B..T` changes any `units/*/unit.json`. |
| **Gate or toolchain moved** | `B..T` may change `scripts/gate-*`, `scripts/lib/gate*` or the toolchain, so the verdict was judged by another gate than the tip's (P-46). | Keep D-075's `gate_version` = tip's and `toolchain_id` = attestation; a gate change in `B..T` refuses. |
| **Ownership / CODEOWNERS** | Unchanged: `owned()` (`train.py:170-180`) runs before any admission; CODEOWNERS is generated from the manifests. | The same check, at `T`. |
| **Distance** | Many merges since `B` grow `key(B..T)` and the chance of a hidden interaction. | `train.shard_admit_max_behind` (proposed 5), tuned from shadow data. |
| **Flake in the confirm** | A red tier 3 could blame an admitted PR wrongly. | The existing quarantine path (`quarantine.proven_flaky`) runs before any revert. |

## 6. Cost of being wrong

An admitted PR can land a tree that breaks the integration branch. Production is frozen (D-054) and a release is one
merge of the integration branch, so the blast is the integration tip until the next tier-3 confirm, not users. That is
why the plan asks for shadow data and a green confirm before release, not for an unconditional rule.
