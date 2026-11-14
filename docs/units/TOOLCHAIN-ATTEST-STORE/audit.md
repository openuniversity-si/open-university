# TOOLCHAIN-ATTEST-STORE: audit

## Entradas
- [intake.md](intake.md): the real problem: `toolchain_id` depends on the store a process reads; resolved when file and shared store attest one id and the strict admission admits.
- [research.md](research.md): the state of the art: hermetic identity over declared inputs (Bazel action keys, Nix store paths).
- Read as inputs only; the findings below are this audit's own.

## Achados
- `scripts/lib/toolchain_manifest.py` `registry_digest()` = sha256 of every registry default **updated with `config.overrides()`**: the overrides of whichever store `OU_CONFIG_STORE` names. Gate (file store) and train (shared store) read different overrides, so `attestation()['toolchain_id']` differs for every head.
- `install_id()` reads `toolchain.*_version` through `config.get`; `toolchain` is a `config.bootstrap_owners` owner, so those are registry defaults already: store-independent.
- Consumers: `gate_keys.toolchain_id` (gate, cache keys), `train_reuse.attested_toolchain` and `train_admit.admissible` (compares `payload.toolchain_id`, then recomputes `input_digest` with it). Nothing reads `registry_digest` outside the attestation.
- `scripts/tests/test_toolchain_pins.py::test_a_local_registry_change_gets_another_id` pins the defect (an override changes the id); it is replaced by a committed-registry test.
- #808 touches `train_admit.py`, `train_verdict.py`, `train.json`, DECISIONS.md: this unit changes none but DECISIONS.md (append D-080 only).

## Distância do estado da arte
- **Already there:** pins (`install_id`), machine and observed binaries are inputs, not runtime state.
- **Missing at base:** the registry part mixes runtime overrides (`config.overrides()`), the one non-hermetic input.
- **Rung:** this PR reaches rung 1 (committed registry only). Still missing: hashing only the owners that are toolchain inputs (rung 2), one content-addressed manifest shared by gate and train (rung 3).
