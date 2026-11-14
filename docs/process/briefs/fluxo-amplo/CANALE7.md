# CANALE7: the engine operates without GitHub: monitoring, control and communication channels (E7, /workspace/torre/redesenho-canal/e7-sem-github.md)

- Owner: lane-1, model claude-opus-5-5, wave 1
- Depends on: CANALE5
- Source: `docs/programs/fluxo-amplo/plan.md`

## Done criteria

- [ ] with api.github.com unreachable a session publishes STATUS, reads its own work, receives a decision and records a result
- [ ] the control plane holds the event route and forge_events has its adapter; GitHub keeps only the code (branch, PR, merge, gate)
