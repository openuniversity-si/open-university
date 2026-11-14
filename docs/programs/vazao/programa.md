# Programa VAZÃO: do degrau 0 ao degrau 1

Programa no sentido do [método](../../padrao/METODO.md) (PDCA). Escrito em 03/11/2026 pela sessão do ciclo SEMENTE, a
partir da sugestão de Daniel das 04:40 BRT: o estado da arte é o piso. Benefício: a vazão do sistema inteiro
(SEMENTE §3). Encerra quando a vazão medida de fora chega a 0,0116 PR/s (0,69 PR/min, 1.000 PRs por dia) sem nenhuma
guarda piorar.

## 1. Avaliação

- **O que se quer:** PRs mergeadas em `mod/roadmap-integration` por unidade de tempo, sem inflar (SEMENTE §3).
- **Medida de hoje** (`scripts/flow-metrics --prs 10` e `--closed-hours`): 0,0043 a 0,0066 PR/s nos últimos 10
  merges e 0,100 PR/min na hora fechada das 03:00 BRT. É de 6 a 7 vezes menos que o degrau 1.
- **O sistema ideal que falhou:** uma fábrica em que o trabalho flui sem fila nem parada. Hoje há uma sessão só e uma
  PR em voo de cada vez (WIP 1). A sessão escreve, o gate julga e o merge acontece, em série.

## 2. Pesquisa (o que o mundo já sabe)

1. **Lei de Little** (teoria de filas): vazão = WIP ÷ tempo de ciclo. Com WIP 1 e um ciclo de cerca de 5 min por PR,
   o teto é 0,2 PR/min. O degrau 1 exige 0,69 PR/min: ou um ciclo de 87 s com WIP 1, o que a escrita de um modelo não
   alcança, ou WIP ≥ 3,5 com o ciclo de hoje. **Nenhuma otimização serial chega ao degrau 1.**
2. **Teoria das Restrições** (Goldratt): achar a restrição, explorá-la sem desperdício, subordinar o resto a ela e
   então elevá-la. A restrição aqui é o tempo do modelo, limitado pela cota. Explorar é tirar dele as esperas e as
   chamadas repetidas. Elevar é pôr mais modelo em paralelo.
3. **Filas de merge com validação especulativa em paralelo:** o SubmitQueue da Uber (EuroSys 2019, *Keeping Master
   Green at Scale*; [CI at Scale: Lean, Green, and Fast, 2025](https://arxiv.org/abs/2501.03440): -53 % de recurso de
   CI e -37 % de espera p95) mantém a principal verde enquanto valida muitas mudanças em paralelo contra as combinações
   prováveis ([desvio de diffs grandes](https://eng.uber.com/blog/bypassing-large-diffs-in-submitqueue/)). As filas
   comerciais juntam PRs em lote e, quando um lote falha, bisseccionam para achar a culpada
   ([Trunk](https://docs.trunk.io/merge-queue/optimizations/batching.md),
   [Aviator](https://docs.aviator.co/mergequeue/concepts/batching),
   [Mergify](https://mergify.com/blog/when-to-outgrow-github-merge-queue)).
4. **Agentes em paralelo:** PRs concorrentes de agentes entram em conflito com frequência: 41,7 % de conflito textual
   entre agentes diferentes num replay de 716 merges, e 27,7 % em outro conjunto de 142 mil PRs (citado por terceiros).
   O conflito semântico, um merge limpo que quebra o build, é o risco maior. A mitigação recomendada é dar a cada
   agente um escopo de diretório disjunto e usar worktrees isolados
   ([arXiv 2607.04697](https://arxiv.org/abs/2607.04697),
   [resumo](https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/),
   [worktrees](https://augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution)).
5. **Seleção de testes:** o estado da arte é a seleção preditiva (Meta 2019,
   [arXiv 2204.10899](https://www.arxiv.org/pdf/2204.10899)): uma fração dos testes com quase todas as falhas. É
   probabilística e pode deixar passar falhas.

## 3. Análise (o estado medido contra o estado da arte)

| Ponto | Estado da arte | Nós hoje | Distância |
|---|---|---|---|
| WIP | muitas mudanças em voo | 1 PR (mais o gate em background, #22) | a restrição pela Lei de Little |
| Principal verde | a fila valida a combinação com a base que vai receber a PR | o gate julga o head da PR; `origin pr merge --expect-head` confere o head, não a base | uma PR julgada sobre a base X entra sobre a base Y sem ser julgada de novo (a classe "base vermelha sem ninguém ver", vista 4 vezes hoje) |
| Conflito entre agentes | escopo disjunto, worktree isolado | worktree por entrega (#22), lane dona de unidades (D-065) | sem lanes em voo, a regra do escopo nunca foi exercitada |
| Seleção de testes | preditiva | por manifestos de cobertura (determinística), mais a bateria inteira à noite | determinística é mais segura; o defeito era cobertura incompleta (#19) |
| Tempo de ferramenta por PR | minutos de CI absorvidos pela fila | ~60 s de gate + ~10 s por push (#21, #17) | já é pequeno perto do tempo do modelo |

Causa da vazão baixa: WIP 1 numa restrição (o modelo) que não pode ficar mais rápida a ponto de compensar.

**Atualização de 03/11 à tarde ([sistema](sistema.md)):** com várias lanes, o tempo de ferramenta deixa de ser pequeno.
O gate usa a CPU inteira da caixa (3 suítes simultâneas levam 346 s cada contra 113 s sozinha), então uma caixa não
passa de ~0,0095 PR/s com a mediana de 105 s por gate, abaixo do degrau 1. A2 continua a escolha; a verificação mais
barata por PR e o lote (A3) passam a ser pré-requisitos dele.

**Cota (medida em 03/11, `scripts/usage --tokens --per-pr`):** a sessão do ciclo gastou, por PR mergeada, ~7,2 mil tokens
de saída, ~20 mil não cacheados e ~3,2 milhões lidos do cache, cerca de 262 mil por mensagem. Quem domina é a releitura do
contexto, não o que se escreve. Uma lane nova (um subagente) começa com um contexto pequeno e paga muito menos leitura
por PR do que a sessão longa. As lanes elevam a vazão por segundo e, ao mesmo tempo, baixam a cota por PR.

## 4. Solução

| Alternativa | Custo | Alcance | Requisitos |
|---|---|---|---|
| A1. Série com pipeline (hoje) | nenhum | teto de ~0,2 a 0,3 PR/min, abaixo do degrau 1 | — |
| A2. N lanes em paralelo com escopo disjunto, entregando por `deliver --branch`, cada merge julgado de novo se a base andou | cota ×N enquanto as lanes rodam; um guarda de base movida no `deliver` | ~N × 0,2 PR/min; N = 4 passa do degrau 1 | cota de Max; unidades independentes prontas |
| A3. Fila de merge especulativa (estilo SubmitQueue) | redesenho do trem (`scripts/train`, parado) | a dezenas de PRs em voo | VM do trem redimensionada (é dinheiro: Daniel) |

**Escolha: A2.** É a única que chega ao degrau 1 sem dinheiro, e A3 só compensa com dezenas de PRs em voo. A2 tem um
pré-requisito de correção que o estado da arte mostra e que nos falta: julgar a combinação com a base que vai receber
a PR. Revisão: se a taxa de conflito ou de base vermelha subir com N lanes, A3 entra.

## 5. Fases

1. **Guarda da base movida:** antes do merge, o `deliver` confere se a base andou desde o início do gate. Se andou,
   junta a base na branch com um merge commit e julga de novo. Fecha quando o teste prova os dois casos e uma entrega
   real passa por ele.
2. **Duas lanes** (com a cota da conta Max, a partir de 04/11): a sessão e um subagente, cada um com um escopo
   disjunto. Fecha quando duas horas fechadas seguidas passam de 0,3 PR/min sem nenhuma guarda pior.
3. **N lanes até o degrau 1:** N sobe enquanto a vazão por lane se mantém e a cota comporta.

Cada fase faz verificação e retrospectiva, e o programa faz a sua no fim.
