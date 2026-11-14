# VAZÃO, fase 2: duas lanes

Fase do [programa VAZÃO](programa.md). Começa com a cota da conta Max (04/11). Encerra quando duas horas fechadas
seguidas passam de 0,3 PR/min (`scripts/flow-metrics --closed-hours 2`) sem nenhuma guarda pior: base verde, nenhum
revert e nenhum incidente aberto sem causa raiz.

## Auditoria técnica (03/11, base `86808ece`)

- **Entrega concorrente:** `scripts/deliver --branch` entrega a partir de um worktree próprio e sempre com a versão da
  base (#22, #24). Ela julga o que entra (#32, provado em #33). Duas entregas ao mesmo tempo não dividem árvore nem
  ferramenta.
- **Gates simultâneos:** `gate.slots_per_vcpu` 0,5 com 4 vCPUs dá 2 slots. Com um gate de ~60 s por ciclo de ~5 min,
  quatro lanes ocupam em média 0,8 slot.
- **Merge:** o `origin pr merge --expect-head` de cada lane é independente. Um conflito com outra lane aparece no merge
  da base que o `deliver` faz antes do gate, e nada entra.
- **Escopo:** a regra é a do estado da arte (programa §2.4): cada lane recebe um conjunto disjunto de arquivos. A lane
  dona de unidades (D-065) é o mecanismo que já existe.

## Planejamento: unidades prontas, com escopos disjuntos

| Unidade | Escopo (arquivos) | Valor |
|---|---|---|
| U1. local-checks em paralelo | `scripts/lib/local_checks.py` e seu teste | cerca de 8 s por push viram ~3 s; com N lanes, N vezes |
| U2. regra de esforço do plano retirada (D-292) | `scripts/lib/effort.py` (só `plan_errors`), `scripts/tests/test_structure_effort.py` e as chaves `effort.plan_*` numa 2ª PR | o último lock que o regime de exceção ainda levanta |
| U3. saída do regime de exceção (D-260) | `config/registry/regime/` | a condição de saída ("GitHub não limita mais o fluxo") foi atingida; sem regime, o teste rodado puro já não mente |
| U4. `gate-dev --why` sem as pendências da era GitHub | `scripts/gate-dev`, `scripts/lib/gate_why*.py` | "base status: unknown (GX-13 not merged)" sai do relato de cada falha |
| U5. a sessão liga o ciclo sozinha | `scripts/cloud/setup.sh` (com uma variável que a sessão autônoma declara) | o hook de Stop fica ativo sem depender da sessão lembrar de `scripts/cycle on` |

U1 e U4 não dividem arquivos com nenhuma outra unidade. U2 vem antes de U3, porque sair do regime com a regra de
esforço ainda ativa recusaria dois planos antigos.

## Execução

Lane A: a sessão (U2, depois U3). Lane B: um subagente num worktree isolado (U1, depois U4). Cada uma entrega por
`scripts/deliver --branch` em background.

## Verificação

`scripts/flow-metrics --closed-hours 2` e a base verde (`scripts/test-suite` na base ao fim da fase).
