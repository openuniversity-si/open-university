# Forge flow compatibility

`operation_demands.json` remains the consumer census and per-adapter behavioral
evidence. `forge_requirements.py` classifies that same declaration: operations are
required unless explicitly optional (`train.calls`) or conditional
(`train.approvals`, when foreign ownership requires approval). Composition includes
`engine_role.lock/unlock` before the train queue. Unknown consumers retain the
existing diagnostic; they are not certified by an empty requirement.

The journal requires `append` and `read`; `recent` is an optional optimization.
These are distinct from forge operations. Each selected journal, board comment
provider and forge adapter must meet its own surface before use. Routing retains
selection and attributes missing forge operations to its concrete main adapter.
A caller that already knows a branch condition passes `conditions` at port
construction, so its conditional demand is checked there too. Presence alone never proves behavior: operation_demands still checks local
behavioral evidence. Contracts must cover active required demand; a conditional
fixture exercises approvals even when current manifests do not activate it.

R3 remains a deliberate patch: lock/unlock and calls still live on the forge
adapter. Follow-up: ARQ-ENGINE-COORDINATION must audit exclusivity and accounting
before migrating them. This work changes neither selection nor production, and
local doubles do not certify remote availability, Origin production or semantic
equivalence of arbitrary providers.
