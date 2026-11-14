# TOOLCHAIN-ATTEST-STORE — intake

## Pedido
Daniel (CEO), 29/10/2026 17:47 BRT, via A Torre (pt-BR, literal): "Chefia, precisamos acelerar isso aí. Não podemos ficar parados assim". Make the toolchain attestation independent of the config store the process reads.

## Intenção
Let the strict D-075 admission admit PRs on a session's verdict, so the train stops taking the slow tier-2 path for every PR.

## Contexto
- The gate attests with `OU_CONFIG_STORE=file` (local registry log); the train with the shared store. `registry_digest()` mixes `config.overrides()` into `toolchain_id`, so the two ids never match (#804 refusal 20:38Z: "toolchain 710c5639… is not the attested f061b4e0…"; D-072 evaluation item 2 on #548).
- #808 (D-079) covers only `train.self_host_paths` PRs. D-078 is #807, D-079 is #808: this unit records D-080.

## Regras
D-025, D-054, D-055, D-065, D-066, D-075 (admission), GX-28 (attestation), D-077 (intake/research), STRUCTURE.md B5.

## Problema real
`toolchain_id` depends on runtime store state, not on the committed inputs. Resolved when the same head attested under the file and the shared store gives one id, a tooling change still changes it, and `train_admit.admissible` admits a session's verdict.

## Lacunas
None that depend on Daniel; the store's runtime overrides keep acting on the gate's behaviour, they just stop being toolchain identity.
