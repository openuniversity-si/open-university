# VAZÃO F36: o trem com lotes na caixa (desenho, 03/11/2026)

Desenho da unidade F36 da [fila](fila.md). Nenhum código muda aqui; as PRs da §4 implementam. Marcação: **[M]** medido
(com a fonte), **[I]** inferido (conta, simulação ou leitura de código ainda não exercida).

## 0. Ponto de partida

- A caixa é este contêiner de 4 CPUs. O `deliver` serializa base, gate e merge pela trava `box_gate` (flock em
  `delivery.gate_lock_path`, F23/F27) e grava `{pr, waited_s, held_s}` no log da trava (F38) **[M, código]**.
- Gate: ~50 s numa PR só de documento, ~100 s numa de código; sozinha, a caixa faz ~36 PRs/h **[M, sistema §3]**.
  p = 0,133 e n_r = 1,25 sobre 82 merges (F24) **[M]**; nos 10 últimos (#104 a #114), p = 0,000 e n_r = 1,00
  **[M, `flow-metrics --guards`, 03/11 19:06 UTC]**. Nessa mesma leitura, `flow-metrics --constraint` responde
  "upstream", com a caixa 0 % ocupada **[M]**. Por isso o lote só liga pela chave medida da §5.
- O trem existe e está parado (não há sessão do papel do trem, a VM está parada e `train.trigger_mode` é `emit_only`).
  Ele já faz quase tudo que F36 pede **[M, código]**:
  - monta o lote na ponta, um commit de merge por PR (`train_git`, `merge_composition`), e o ordena por `critical_first`;
  - julga o lote com um tier 2 (`scripts/gate-batch --tier 2`, plano da união) e bissecta por prefixos (`engine_role.first_red`);
  - expulsa o culpado (`pr.ejected`) e faz o merge com `--match-head-commit`, seguido da prova de árvore;
  - também traz flake e quarentena, reconstrução quando a base anda (`train.rebuild_max`) e parada nas classes `env`/`contract`.
- `scripts/train queue` lê hoje a fila do Origin pelo diário git-ref (D-296) **[M, 03/11 19:01 UTC: listou #114]**.

## 1. O que roda onde

- **O trem roda na caixa, dentro da trava da caixa, sem VM e sem processo próprio.** Quem o põe para andar é o `deliver`
  que ganha a trava com 2 ou mais entregas esperando (o "líder", como no *group commit* de bancos de dados).
  O líder roda `scripts/train run --box`: um lote, até o fim (mergeado, expulso, conflitado ou parado). Depois devolve a trava.
- **Ninguém inicia nem para o trem.** Não há `serve`, laço, sweep nem pausa. O evento é a soltura da trava
  (`flock`): o kernel acorda o próximo `deliver` que espera, e ele vira o líder seguinte se ainda houver fila (D-065 (1)).
  Um líder que morre solta a trava pelo kernel, e o seguinte relê o estado das PRs no forge antes de montar o lote.
- **Um lote por liderança.** O líder não drena a fila inteira, para que o `deliver` da sua lane volte logo. Quem chegou
  durante o gate lidera o próximo lote.
- A trava `train.lock_ref` (git) continua por dentro da trava da caixa, sem mudança. Ela impede que um runner religado
  noutra máquina faça merge ao mesmo tempo. Custa alguns segundos por lote **[I; medir no passo `train:batch`]**.

## 2. Admissão: quem vai para o trem

- **As lanes não mudam nada.** Continuam chamando `scripts/deliver --pr N --branch B` em segundo plano. O `deliver` passa
  a entrega adiante quando há fila:
  1. Antes de pedir a trava, grava `pr-N.json` `{pr, branch, head, pid, at}` na fila da caixa (`delivery.box_queue_dir`).
  2. Ao ganhar a trava, lê a fila. Se outro líder já resolveu a sua PR, imprime o resultado
     (`pr-N.result.json`: mergeada, expulsa, conflitada ou recusada) e sai com 0 ou 1, sem gate.
  3. Com uma só entrega viva, ou com `delivery.batch` desligado, segue o caminho de hoje sem mudança:
     merge da base no ramo, `gate-dev` no head exato, até 3 rodadas e `--expect-head`.
  4. Com 2 ou mais entregas vivas (pid vivo e head igual ao do `ls-remote`) e o lote ligado (§5), vira o líder.
     O lote leva até k(p) entregas (§3), as mais antigas primeiro.
- A fila da caixa é coordenação de processos, como a própria trava: vive enquanto os processos esperam e não guarda
  estado do fluxo. O registro continua no forge (`pr.merged` com `batch_id`, `train.batch.*`, `pr.ejected`), por isso
  D-065 (1) se mantém. As entradas do trem são montadas dessa fila (`train_queue.box_entries`), não do `pr.ready`, que
  exige um `gate.passed` por head, justamente o gate que o lote economiza.
- **Antes de entrar no lote, cada membro passa pelo que o gate julga só no head da PR:** o merge da ponta no ramo
  (o `_with_base` do `deliver`, empurrado sem hook, porque o FP1 do `commit-check` recusa um head atrás da base) e a
  parte de PR do `structure check` (`commit-check --pr N` e o corpo: plano, trailers, Premises). O `gate-batch --tier 2`
  roda sem contexto de PR e não vê essa parte **[M, código]**. Um membro recusado sai com o resultado `recusada`, como
  um gate vermelho do `deliver`. Custa alguns segundos por membro **[I; medir]**.

## 3. O lote

- **Combinação:** a ponta, mais um commit de merge por membro (já ressincronizado) na ordem `critical_first`. É o
  `start_batch` de hoje, sem mudança. Um membro que não entra na combinação sai com `pr.conflicted` (arquivos nomeados)
  e com o resultado `conflitada`.
- **Julgamento:** um `gate-batch --tier 2` no head combinado. Hoje cada execução do tier 2 ganha caches vazios
  (`engine_role.CommandGate`) e paga a suíte a frio, ~96 a 113 s, mesmo num lote só de documento **[M, código; D-121]**.
  Na caixa ele passa a usar o cache por conteúdo da caixa, o mesmo do `gate-dev` do `deliver` (F19), que D-076 (a) já
  permite no tier 2 (chave `train.tier2_test_cache`: `fresh` | `box`). Com isso o custo de um lote fica perto do custo
  do membro mais caro **[I; medir `held_s` do lote contra o da entrega sozinha]**.
- **Bissecção esperta:** a busca por prefixos do trem já não reexecuta o lado sabidamente vermelho. Ela acha o primeiro
  prefixo vermelho com ⌈log₂ k⌉ execuções e culpa o membro sem rodá-lo sozinho. Muda uma coisa: **o prefixo provado
  verde antes do culpado é mergeado na mesma liderança** (`merge` sobre `commits[f-1]`, que já foi julgado). Hoje ele
  volta inteiro para a fila. O resto depois do culpado volta para a fila da caixa e entra no próximo lote.
  Simulação desta política com fila cheia e vermelhos independentes **[I, Monte Carlo de 200 mil PRs]**:

  | p | k=2 | k=3 | k=4 | k=5 | k=8 | box.md (bissecção de subconjuntos, k=5) |
  |---|---|---|---|---|---|---|
  | 0,05 | 0,56 | 0,43 | 0,37 | 0,34 | 0,30 | 0,36 |
  | 0,133 | 0,67 | 0,61 | **0,57** | 0,59 | 0,59 | 0,59 |
  | 0,20 | 0,76 | 0,76 | 0,74 | 0,81 | 0,85 | — |
  | 0,30 | 0,89 | 0,99 | 0,99 | 1,15 | 1,22 | — |

  As células são execuções de gate por PR resolvida. A política de prefixos com merge do prefixo verde iguala a conta
  da pesquisa (~0,59 com p = 0,13) sem um algoritmo novo. Com p = 0,133 e T = 100 s, a caixa passa de 36 para ~60 a 63
  PRs/h processadas **[I]**.
- **Tamanho adaptativo:** k = o que espera, limitado por k_max(p). A tabela fica em `train.batch_size_by_red`, e p é o de
  F24 nas últimas 50 PRs resolvidas, lido pelo líder a cada liderança (um evento, nunca um relógio):

  | p | ≤ 0,10 | ≤ 0,15 | ≤ 0,25 | > 0,25 |
  |---|---|---|---|---|
  | k_max | 8 | 4 | 2 | 1 (lote desligado) |

  `train.bisection_max_runs` = 4 cobre k = 8, e o trem já recusa um tamanho que não cabe. Com no máximo 3 frentes no
  gate (I-2012f37d), o k real fica em 2 ou 3 **[I]**.
- **A prova de cada PR mergeada.** Num lote, o head de cada PR não é julgado sozinho. A prova passa a ser **o gate verde
  do commit do lote (ou do prefixo provado) cuja árvore a ponta recebe**: `tree(ponta) == tree(testado)`, a prova de
  árvore que já existe, mais `--match-head-commit` do head que entrou no lote. O `pr.merged` leva o `batch_id`, que liga
  a PR ao `train.batch.green` e ao veredito do tier 2. É a regra do trem de D-065 (4) e (5), hoje suspensa pela regra
  "a sessão faz o merge com o gate no head exato" (AGENTS.md, Delivery flow). Religá-la na caixa pede **uma decisão
  nova, antes do código** (o próximo número livre, hoje D-297). Ela registra:
  - (a) a prova por lote na caixa;
  - (b) a fila da caixa como coordenação, não estado;
  - (c) o tier 2 com o cache por conteúdo da caixa (D-076 (a));
  - (d) que, quando F37 exigir no Origin um check no head exato, o trem publica esse check em cada membro, citando o
    lote e o commit testado.

  A VM e o runner continuam parados.

## 4. Código: reusado, alterado, removido, e as PRs

- **Reusado sem mudança:**
  - em `train.py`: `start_batch`, `tier2`, `judge`, `halt`, `flake`, `refused` e a prova de árvore;
  - nos módulos: `train_git`, `merge_composition`, `train_queue.critical_first`, `train_ownership`, a trava
    `train.lock_ref` com `forge_git_ref`, `gate_batch` e `quarantine`;
  - do `deliver`: `box_gate` e o seu log, `_with_base` e o caminho de uma PR só.
- **Alterado:**
  - `Train.run_batch`/`bisect`: merge do prefixo verde;
  - `CommandGate`: o cache do tier 2 vira escolha por chave;
  - o k vem de p;
  - nova fonte de fila: a fila da caixa;
  - `deliver`: passa a entrega adiante e lidera;
  - `flow_metrics`: guardas cientes de lote e a trava ocupada por lotes.
- **Removido nesta unidade:** nada. Fora do modo caixa ficam sem uso o modo `verdict` (ressincronização, re-veredito,
  shard, bootstrap, self-host), `train serve`/wake e `scripts/train-loop`. Saem numa PR própria depois de duas semanas
  do lote ligado, pela regra de prova de ausência (D-289).

| # | PR | Escopo | Tamanho |
|---|---|---|---|
| 1 | decisão: o trem com lotes na caixa | registro `docs/domain/decisions/D-297.md` (a)–(d) (os registros são o caminho desde D-217; a tabela não recebe a linha porque `decision-table --write` recusa os números repetidos D-258, D-272 e D-283), seção "Na caixa" em `docs/operations/train.md`, frase do Delivery flow em `AGENTS.md` | S, só docs |
| 2 | trem: o prefixo provado verde entra junto com a expulsão | `train.py` (`run_batch`, `bisect`), `scripts/tests/train/test_batch.py` | S |
| 3 | trem: tier 2 com o cache por conteúdo da caixa | `engine_role.CommandGate`, chave `train.tier2_test_cache` (padrão `fresh`), teste | S |
| 4 | flow-metrics: guardas e trava cientes de lote | p e n_r contam o lote (1/k execução por membro, vermelho = `pr.ejected` culpado), execuções por PR resolvida, lotes verdes, `held_s` de lote; `test_flow_metrics.py` | S |
| 5 | trem: k pelo vermelho observado | `train.batch_size_by_red`, leitura do p da PR 4, teste da tabela e do limite de bissecção | S |
| 6 | trem: fila da caixa e `train run --box` | `train_queue.box_entries`, `--box` toma a trava da caixa (`box_queue.hold`; sob o `deliver` que já a segura, herda-a por `TOWER_BOX_LOCK_HELD`, porque um segundo `flock` esperaria pelo próprio pai), ressincroniza e checa cada membro, um lote, grava `pr-N.result.json`; testes com o forge `file` | M |
| 7 | deliver: passa a entrega adiante quando há fila | fila da caixa, líder/seguidor, `delivery.batch` (`off` \| `auto`, padrão `off`), lote no log da trava; `test_deliver.py` | M |
| 8 | trem: check do lote em cada membro (só se F37 já exigir o check) | o adaptador do Origin publica o check run no head de cada membro citando lote e commit testado | S |

Ordem: 1 → 2 → 3 → 4 → 5 → 6 → 7 (→ 8). Cada uma fica verde sozinha, e até a 7 nada muda no fluxo, porque nada chama
`--box` e `delivery.batch` fica `off`.

## 5. A chave medida

- **Liga** (`scripts/config set delivery.batch auto --reason "<linha do medidor>"`) quando `flow-metrics --constraint`
  nomeia a caixa como restrição (ocupada ≥ 70 % na última hora, F38) e o p de F24 nas últimas 50 está ≤ 0,25. Com
  `auto`, cada liderança ainda exige 2 ou mais entregas vivas e k_max(p) ≥ 2. Um par de passagem também ganha
  (0,67 execução por PR com k = 2) **[I]**.
- **Desliga** (`off`, uma chave, volta ao `deliver` de hoje) com qualquer uma destas condições, todas lidas pelo líder
  ou pelo medidor:
  - p > 0,25 nas últimas 50;
  - execuções de gate por PR resolvida ≥ 1,0 nos últimos 10 lotes (o lote parou de ganhar);
  - uma ponta vermelha no shadow (D-157) depois de um lote verde. Isso abre incidente com causa raiz (D-081);
  - a prova de árvore falhou (o trem já para: `train: halted`).

## 6. Riscos e como cada um é medido

| Risco | Medida | Resposta |
|---|---|---|
| Vermelhos correlacionados (interação entre PRs) acima do modelo independente **[I]** | execuções por PR resolvida e share de lotes verdes (PR 4) contra a tabela da §3 | k_max menor; desliga em ≥ 1,0 |
| O cache por conteúdo no tier 2 reaproveita um PASS cuja chave não cobre uma entrada **[I]** | gate-shadow de cada ponta nova (D-157) e o gate-noite; ponta vermelha depois de lote verde | `train.tier2_test_cache fresh`; incidente |
| Um lote vermelho atrasa a fila: até ⌈log₂ k⌉+1 execuções, ~300 s com k = 4 **[I]** | `waited_s` por entrega no log da trava, p90 | k_max menor se o p90 passar de 2× o da entrega sozinha |
| A ressincronização e as checagens por membro comem o ganho **[I]** | tempo por membro antes do tier 2 (passo medido `train:admit`) | cortar o que repete o pre-push |
| O Origin recusa o merge de um membro ou a base anda durante o lote | linhas `refused` e reconstruções (`train.rebuild_max`) | o trem já reconstrói ou para |
| Líder morre no meio dos merges **[I]** | entradas sem resultado com o pid morto; `pr.merged` já emitidos | o próximo líder relê o estado no forge; merge por head é idempotente |
| Um flake segura k PRs | `test.flaked` por lote | quarentena existente; o lote volta à fila |
| F37 passa a exigir check no head exato e recusa membros | recusas do forge com motivo de check | PR 8 antes de ligar F37 |
| A caixa não é a restrição (hoje não é **[M]**) | `flow-metrics --constraint` | o lote fica desligado e não custa nada |

## 7. Decisões tomadas aqui (reversíveis)

- **O líder é o `deliver`, não um processo do trem.** Assim não existe serviço para iniciar, vigiar ou reiniciar, e o
  evento é a soltura da trava.
  Reversão: a chave `delivery.batch off`.
- **Merge do prefixo verde em vez da bissecção de subconjuntos da box.md §5.** Dá o mesmo custo com p = 0,13 **[I]**
  e reusa `first_red`.
  Reversão: reverter a PR 2.
- **Ordem por atribuição fica para depois.** Pôr por último os membros que `gate_batch.attribute` implica daria
  ~0,46 execução por PR com p = 0,133, supondo 80 % de acerto **[I]**. Primeiro é preciso medir o acerto da atribuição
  nos lotes vermelhos.
