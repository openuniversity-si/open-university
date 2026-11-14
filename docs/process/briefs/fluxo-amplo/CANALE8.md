# CANALE8: one forge port of six operations (change, identity, append, read, set_status, merge); Origin implements all six; the switch is forge.adapter (/workspace/torre/redesenho-canal/e8-adaptador-total.md)

- Owner: lane-1, model claude-opus-5-5, wave 1
- Depends on: CANALE7
- Source: `docs/programs/fluxo-amplo/plan.md`

## Done criteria

- [ ] the same test file runs against the GitHub and the Origin adapters, and passes on both with api.github.com refusing every call
- [ ] scripts/config set forge.adapter origin changes no train, gate, lane or caller module
