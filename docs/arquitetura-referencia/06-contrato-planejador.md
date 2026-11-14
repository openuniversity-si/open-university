# 06. O contrato do planejador e do conjunto de instruções da IA

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

Entregável 5. A interface que o planejador (C02) e o conjunto de instruções da IA (C03) têm que cumprir para a fábrica
chegar a 10^9 PRs/s, sem desenhar a lógica deles: essa lógica é a inovação da Torre e o próximo projeto. O que está
aqui é o que a arquitetura exige e mede de fora.

## 1. Fronteira

- **O planejador** recebe intenções (C01) com orçamento e devolve **decisões**: transformações com o predicado que
  escolhe os lugares, o programa que aplica a mudança, os conjuntos de leitura e escrita, o plano de certificação e a
  amplificação esperada. Ele não aplica, não verifica, não grava e não coordena; esses são os passos 2 a 5.
- **O conjunto de instruções** é o que toda sessão de IA da fábrica recebe: papéis, ferramentas permitidas, políticas,
  esquemas de saída e a bateria de avaliação. É conteúdo versionado, não código da fábrica.
- **O que a arquitetura entrega a eles:** o índice para contar e enumerar lugares (C04), o histórico do ledger (o que
  mudou, onde houve conflito), o orçamento disponível (C05), o que está em voo (claims, C24), os vereditos de
  certificação e de amostra (C10, C13, C14) e o custo medido (C27).

## 2. A interface

| Operação | Entrada | Saída | Quem chama |
|---|---|---|---|
| `estimate(intenção, snapshot)` | intenção, snapshot | amplificação esperada, custo em tokens e núcleo·s, partições tocadas, conflitos com o que está em voo | C05 antes de admitir |
| `propose(intenção, orçamento, snapshot)` | intenção admitida | fluxo de decisões | o workflow da intenção (C22) |
| `revise(decisão, veredito)` | a decisão e o veredito da certificação, da amostra ou de V3 | decisão revista ou retirada, com o motivo | o workflow da decisão |
| `resolve(papel, tipo de tarefa)` | papel, tipo | a versão do conjunto de instruções, por hash | toda sessão de IA (C07) |

Todas as operações são idempotentes pela identidade da intenção ou da decisão e emitem os eventos do envelope do motor
([contracts/events/envelope.v1.json](../../contracts/events/envelope.v1.json)): `decision.proposed`,
`decision.admitted`, `decision.certified` ou `decision.rejected`, `decision.wave`, `decision.halted`,
`decision.reverted`, `decision.closed`.

## 3. A decisão: o que ela tem que conter

| Campo | Exigência | Por que (de onde sai) |
|---|---|---|
| `kind` | `transform` (programa aplicado a lugares), `generate` (código a partir de especificação), `search` (candidatos com avaliador automático) ou `patch` (A = 1, um lugar só) | o caminho A = 1 continua valendo (RF-18) |
| `program` | hash do programa, linguagem e hash do toolchain; **função pura**: sem entrada e saída externas, sem relógio, sem aleatoriedade sem semente | a instância é função pura (P2, RNF-09) |
| `sites` | predicado sobre o índice, a cardinalidade esperada e a distribuição por partição | a enumeração (C04) e o dimensionamento das ondas |
| `write_set`, `read_set` | declarados, conferíveis pelo V0; podem sobrar, **não podem faltar** | a validação otimista (P5, RF-08) |
| `certificate_plan` | classe (prova, validação de tradução, testes de propriedade, ou V2 em toda instância), as propriedades e os oráculos, o custo previsto | certificar uma vez (P6, RF-05) |
| `waves` | tamanhos e critérios de observação, ou a política padrão | expansão progressiva (P7, RF-07) |
| `inverse` | como desfazer; o padrão é restaurar a pré-imagem onde o conteúdo ainda é a pós-imagem | rollback por decisão (RF-11) |
| `depends_on` | decisões cujo resultado esta lê | rollback em cascata (RF-17) |
| `utility` | o valor esperado por instância e a métrica que o mede | a vazão não se infla (semente §3) |
| `budget` | tokens gastos (T_d), núcleo·s pedidos, dinheiro | admissão (C05) e o custo por PR |
| `provenance` | modelos, hash do conjunto de instruções, hashes dos prompts, tokens, assinatura | segurança e auditoria (RF-15) |

## 4. Os requisitos e as metas

A coluna 10^9 é a meta de projeto; as outras mostram que o mesmo contrato vale em todos os degraus, só com números
diferentes ([05 §5](05-orcamento-e-degraus.md#5-custo-por-degrau)).

| ID | Requisito | 1/min | 1/s | 10^3/s | 10^6/s | 10^9/s |
|---|---|---|---|---|---|---|
| PC-01 | Vazão de decisões (capacidade de projeto, ρ = 0,75) | 0,022/s | 0,13/s | 1,33/s | 13,3/s | 1,33 × 10^3/s |
| PC-02 | **Amplificação efetiva** A = PRs mergeadas ÷ decisões de IA, contando as que falham | ≥ 1 | ≥ 10 | ≥ 10^3 | ≥ 10^5 | **≥ 10^6** |
| PC-03 | Tokens de IA por decisão (T_d, leitura de cache inclusa) | ≤ 10^6 | ≤ 10^6 | ≤ 10^6 | ≤ 3 × 10^5 | **≤ 10^5** |
| PC-04 | Tokens de IA por PR mergeada (T_d ÷ A), o invariante que junta PC-02 e PC-03 | ≤ 10^6 | ≤ 10^5 | ≤ 10^3 | ≤ 3 | **≤ 0,15** |
| PC-05 | Instâncias dentro de uma partição só | — | ≥ 99 % | ≥ 99,9 % | ≥ 99,99 % | ≥ 99,99 % |
| PC-06 | Sobreposição de escrita entre decisões em voo | — | ≤ 5 % dos lugares | ≤ 1 % | ≤ 1 % | ≤ 1 % |
| PC-07 | Decisões que passam na certificação (y_d) | — | ≥ 0,5 | ≥ 0,7 | ≥ 0,7 | ≥ 0,7 |
| PC-08 | Instâncias que passam no V0 | — | ≥ 0,9 | ≥ 0,9 | ≥ 0,9 | ≥ 0,9 |
| PC-09 | Custo de certificar uma decisão (com a amostra) | ≤ 450 núcleo·s por PR (o gate de hoje) | ≤ 10^3 núcleo·s | ≤ 10^3 | ≤ 10^3 | **≤ 10^3** (≤ 500 de certificação + ≤ 50 instâncias de ≤ 10) |
| PC-10 | Cobertura do certificado | o gate inteiro | ≥ 99 % das classes de lugar | ≥ 99 % | ≥ 99 % | ≥ 99 % |
| PC-11 | Decisões revertidas | — | ≤ 1 % | ≤ 1 % | ≤ 1 % | ≤ 1 % |
| PC-12 | Retrabalho (PRs revertidas ou corrigidas ÷ mergeadas, 24 h) | a guarda de hoje | ≤ 10^-2 | ≤ 10^-3 | ≤ 10^-3 | ≤ 10^-3 |
| PC-13 | Intenção → primeira decisão | p50 ≤ 30 min | p50 ≤ 10 min | p50 ≤ 5 min | p50 ≤ 5 min | p50 ≤ 5 min |
| PC-14 | Custo de IA por PR mergeada | ≤ US$ 0,28 | ≤ US$ 0,03 | ≤ US$ 3 × 10^-4 | ≤ US$ 10^-6 | **≤ US$ 2 × 10^-8** |
| PC-15 | Valor realizado medido numa amostra de instâncias | toda PR | ≥ 1 % | ≥ 0,1 % | ≥ 10^-4 | ≥ 10^-5 |

**A meta de amplificação que 10^9 exige, numa linha:** A ≥ 10^6 com T_d ≤ 10^5, ou seja, **no máximo 0,15 token de IA
por PR mergeada** em média; o motor hoje gasta ~10^6. Se o planejador só conseguir T_d ≈ 10^6, a exigência sobe para
A ≥ 10^7. A conta está em [05 §4](05-orcamento-e-degraus.md#4-a-ia-capacidade-do-mundo-e-a-amplificação-que-fecha-a-conta).

Os requisitos qualitativos que valem em todo degrau:

- **PC-16 Tamanho certo.** Cada instância é mergeável e revertível sozinha, toca uma partição, cabe no limite do V0 e
  tem valor próprio declarado em `utility`. Partir uma mudança só para contar mais PRs é inflação e é medido (PC-15).
- **PC-17 Independência declarada.** Nenhuma dependência oculta: o que a instância lê está em `read_set`. Uma violação
  pega pelo V0 ou pela validação otimista conta como defeito do planejador, não da instância.
- **PC-18 Determinismo conferido.** Uma fração das instâncias é gerada duas vezes, em máquinas diferentes; resultados
  diferentes param a decisão.
- **PC-19 Segurança.** O planejador nunca lê conteúdo não confiável direto (separação entre controle e dados, [03 §10](03-arquitetura.md#10-segurança));
  nenhuma sessão junta dado privado, conteúdo não confiável e comunicação externa; nenhum segredo no contexto.

## 5. O conjunto de instruções da IA

| ID | Requisito | Meta |
|---|---|---|
| PI-01 | Versão imutável, endereçada por conteúdo e assinada; toda decisão cita o hash da versão que a produziu | 100 % das decisões |
| PI-02 | Prefixo compartilhado e estável, para o cache de prompt pagar a maior parte | ≥ 90 % dos tokens de uma sessão como leitura de cache (hoje ~94 % numa sessão de agente [A9]) |
| PI-03 | Esquemas de saída: toda saída de planejamento é uma decisão válida pelo esquema da seção 3 | 0 decisões fora do esquema chegam à certificação |
| PI-04 | Ferramentas por capacidade, com privilégio mínimo por papel | nenhuma ferramenta fora da lista do papel |
| PI-05 | Bateria de avaliação: uma versão nova só é promovida se, num conjunto de decisões de referência, não piorar A, T_d, y_d nem o retrabalho | promoção só com a bateria verde |
| PI-06 | Promoção em ondas, como código: a versão nova começa numa fração das decisões | ≤ 1 % das decisões na primeira onda |
| PI-07 | Medida por versão: A realizado, T_d, y_d, tokens por PR mergeada, custo | em C27, por versão |

## 6. Como o contrato é medido

Tudo sai do ledger e dos eventos, nunca do relato da sessão (semente §6, verificação externa): a amplificação realizada
por decisão e no todo, os tokens por PR mergeada, a taxa de certificação, a taxa de V0, a sobreposição em voo, a fração
entre partições, o retrabalho, as decisões revertidas, o valor realizado na amostra e o custo de IA por PR. É o placar
do planejador em cada degrau e o instrumento do próximo projeto.
