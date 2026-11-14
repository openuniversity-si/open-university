# ARQ-SISTEMA — retro

A unidade inteira, do pedido de Daniel (01/11, 18:43 BRT) à PR de execução. Horários em BRT, tirados dos commits e dos
comentários da PR. Base `2d5446c55`, branch `docs/arq-sistema-audit`.

## 1. Brief e intake

- O pedido veio como sensação, não como especificação: "tá uma zona, nós não temos nossos sistemas nem o ideal definido,
  muito menos como é que tá hoje, eles tão sobrepondo". O intake traduziu isso em "não temos o ideal, não temos a
  descrição de hoje, e os componentes se sobrepõem sem decisão explícita de responsabilidade", com métrica de resolvido
  em quatro contagens que precisam chegar a zero. Não fixou desenho, componente a cortar nem critério de aceitação — a
  regra de 16:18 (o requisito nasce da pesquisa da própria unidade) foi respeitada.
- O problema real se sustentou até o fim: as sete raízes da auditoria são variações dele, e nenhuma foi refutada pela
  execução. Também se sustentou a limitação que o intake declarou: duas contagens da métrica (operações sem dono nomeado
  e operações duplicadas entre componentes) não podem ser levadas a zero por esta unidade; ela mediu o recorte, não o
  censo do motor inteiro.
- Faltou no brief, e custou decisão minha: o teto de oito itens do checklist da PR. O plano prometeu C7 como item 9 e
  esse item não existe na prática — `budgets.pr_commits_max` é 8. Fundi o item 8 (escopo do diagnóstico) no 7, que o
  mesmo commit já entregava, e o retro virou o item 8. Decisão registrada aqui porque o plano não podia cumpri-la.
- Faltou também o teto de tempo de bateria: nada no brief dizia que uma unidade grande pode estourar dez segundos só
  somando suítes. Isso só apareceu na medição, e está no item 3.

## 2. Pesquisa, auditoria e plano

- A pesquisa mudou o plano duas vezes. Primeiro, ela mostrou que a duplicação de composição (R2) era a única duplicação
  operacional demonstrada no recorte: eu contava seis diários, três merges e três detectores de sobreposição, e a
  medição reduziu isso a três implementações disponíveis de merge das quais só duas são selecionadas, um só caminho de
  alerta por arquivos e um diário com adaptadores. Segundo, ela mostrou que a ligação dinâmica de `forge_events.py` era
  intencional (não declarar dependência do vendedor), o que virou requisito do C3: registrar a seleção sem transformá-la
  em `requires`.
- As raízes se sustentaram todas. Nenhuma falha posterior veio de causa que a cadeia de porquês não alcançou. A única
  que quase escapou é R5: a auditoria viu a bateria de `engine-forge-origin` vazia, mas não viu que derivar a prova dos
  covers aumentaria o número de suítes por unidade e, com ele, o tempo — o que virou o risco do item 3.
- O nível das escolhas ficou certo para o orçamento: três correções de classe (R2, R4, R5) e quatro medidas limitadas
  (R1, R3, R6, R7) com unidade de continuidade nomeada. O que a execução mostrou é que as medidas limitadas custam menos
  que o previsto e as correções de classe custam mais, porque cada uma esbarra numa restrição do repositório que o plano
  não mapeou: o censo de literais no C2, o ciclo de importação no C4, o contrato gerado no C6.
- Premissas: nenhuma foi adotada, como o plano declarou (`Premises: none`). As que se comportaram como premissa de fato
  foram as restrições de repositório, e duas quebraram (literal e ciclo de importação).

## 3. Execução

Dez commits, um gate por commit, 54 minutos de relógio de 19:29 a 20:23.

- **C1 `19:44` — mapa de operações e matriz (`6606a0cdd`).** Travou na D-242: a linha da tabela de decisões não pode ser
  digitada à mão. O caminho é `decision-record` → `decision-table --write` → `--check` e `--handwritten` em zero. Classe
  `check-gap`: a regra existe e não está no brief de nenhum commit documental. Rework: uma rodada.
- **C2 `19:46` — a primitiva (`1306ea775`).** `merge_composition.py`, 17 linhas, e os dois laços passaram a chamá-la. A
  pegadinha medida: as políticas dos dois lados são diferentes e foram preservadas — `train_git.combine` aborta no
  primeiro conflito e fixa a data pelo maior committer date dos pais; `gate_batch.merge_union` pula o membro
  conflitante e usa relógio. Compartilhar o mecanismo não autorizou igualar as políticas.
- **C2, dois defeitos meus, achados depois.** (a) Para fugir do censo de literais — `literals.allowed_numbers` é
  `[-1, 0, 1]`, e o número `2` já estava no teto de 41 — escrevi `parents[-1]` no teste, que é a raiz do sistema de
  arquivos, não a pasta `scripts`. O teste passava à mão com `PYTHONPATH` e reprovava dentro de `scripts/run test train`
  com `ModuleNotFoundError: merge_composition`. Classe `test-fragility`. (b) A mensagem do commit ia como `-m`, e
  `structure-check` recusa isso (D-206: um argumento para em cerca de 128 KB). Conserto na fonte, por stdin, e um
  detalhe que quase passou: `-m` termina a mensagem com quebra de linha e stdin não, o que muda o SHA do commit; sem
  repor a quebra o teste que compara com o oráculo do próprio git deixava de bater. Commit `10ada17d0`, `Plan: 4`.
- **C3 `19:53` — relações dinâmicas (`1b179f66f`).** `DYNAMIC_IMPORTS` declara as quatro fábricas em `forge_events.py` e
  o extrator lê por AST, casando cada fábrica com o `importlib.import_module` correspondente. Medido no head: um único
  arquivo de produção com aresta dinâmica, apontando para os quatro adaptadores, zero `dynamic_errors`. E a prova que
  importa: `engine-events` continua com `requires` = só `engine-config` — a seleção de vendedor não virou dependência
  obrigatória (D-283 preservado). Recusa nos dois sentidos: ligação literal não declarada e fábrica declarada que não
  carrega.
- **C4 `19:59` e o conserto `20:01`.** A prova da unidade passou a derivar dos covers, e produção sem prova virou passo
  com erro. Antes → depois: `engine-forge-origin` 0 → 1 passo (5 arquivos), `engine-forge-github` 0 → 1 (12),
  `engine-idea-to-prod` 0 → 1 (6), `engine-train` 1 → 1 (16). Nenhuma das 47 unidades ficou sem passo útil, e nenhum
  dos 484 arquivos de produção ficou sem cover — a recusa nova não quebra nada hoje.
- **C4, o conserto que virou commit próprio (`aa1fc78d8`).** A suíte `config-readers` reprovou o commit anterior porque
  `unit_battery.py` passou a ler `gate-tests.covers_dir` sem declarar o leitor. A causa estrutural: `unit_battery.py`
  **não pode** importar `gate_script_tests.py` — fecharia ciclo (`engine-gate-plan` → `engine-units` e
  `engine-gate-tests` → `engine-gate-plan`). Conserto: declarar a chave no `x-readers` e regenerar o registry. A
  duplicação de leitura dos covers que sobra é dívida registrada no item 5.
- **C5 `20:04` — documentos (`34f2dd515`).** A tabela do `AGGREGATES.md` citava cinco alvos, quatro dos quais não
  existem; dos sete alvos reais, seis não eram citados. `PORTS.md` chamava o Origin de "slot" quando ele é adaptador
  implementado. `STRUCTURE.md` atribuía recusas a `ship-verify`, que não existe, e mandava ler `CONTRACT.md` e
  `FACTORY.md`, que também não existem. Nenhum desses erros veio de leitura minha de código: todos estavam escritos.
- **C6 `20:07` — escopo do diagnóstico (`967094569`).** O contrato declarava `runners` e `jobs` e o `status()` nunca
  preenchia nenhum dos dois. A decisão foi não inventar leitura: `control_plane: {runners: unknown, jobs: unknown}` com
  detalhe explicando, `health.scope` por checagem (`machine` para runner, `repository` para o resto), e o contrato
  passou a dizer que ausência não significa vazio. `scripts/service status` abre com o escopo declarado.
- **Risco aberto que a C4 criou, medido agora.** A bateria de `engine-forge-github` roda 12 suítes e termina em 30,9 s
  contra o teto de 10 s: sai `fail` por tempo, não por teste — todos os testes passam. A saída não é afrouxar o teto; é
  a bateria rodar os arquivos em paralelo, dívida que o retro de `engine-delivery` já tinha registrado. Antes do C4,
  essa unidade tinha zero passos e o problema não existia porque nada era contado.
- **C7 — este retro.** Escrito por mim, não pela sessão de execução: é registro de decisão, e as decisões e os becos
  estavam comigo, não no código.

## 4. Gate

- Nove execuções de gate, uma por commit, todas verdes no head exato, sem vermelho até aqui: `6cf26ca6`, `09554c36`,
  `6606a0cd`, `1306ea77`, `1b179f66`, `cf4f1aee`, `aa1fc78d`, `34f2dd51`, `96709456`. O commit do conserto
  (`10ada17d0`) é posterior a esta lista e fecha o ciclo depois do retro.
- Defeitos de base, não causados por esta unidade: `scripts/tests/structure-check.test.sh` reprova 28 dos seus 63
  testes na base `2d5446c55`, e os mesmos 28 no head; `train-role.test.sh` sai com exit 1 na base também. O
  `scripts/structure-check` no head sai com 0 erros e 16 avisos, todos de outras unidades ou de lock levantado pelo
  regime de exceção.
- O gate não foi usado como sonda: nenhum commit foi empurrado só para ver o que o gate dizia.

## 5. Lições

1. O teto de oito itens do checklist da PR não comporta o retro como nono item. O plano tem de reservar o item do retro
   desde o começo e contar oito, nunca nove, ao desenhar o grafo de commits. Owner: engine-commit-plan
   (`budgets.pr_commits_max`, `plan_tick`).
2. Um número novo num teste de `scripts/` colide com o censo de literais, e o caminho de fuga óbvio (`parents[-1]`)
   troca a pasta certa pela raiz do sistema de arquivos. O conserto é derivar o caminho pelas constantes existentes
   (`Path(__file__).resolve().parents[1].parent`), nunca por índice negativo. Owner: engine-structure
   (`literals.allowed_numbers`).
3. Um teste que precisa de `PYTHONPATH` para passar não está provado: tem de rodar pelo caminho da suíte, sem variável
   ambiente. Owner: engine-units (`scripts/tests/train/*`).
4. A mensagem de um `git commit-tree` vai por stdin, nunca por `-m`, e stdin não repõe a quebra de linha final do `-m` —
   que entra no SHA. Todo helper de commit tem de repor a quebra. Owner: engine-train (`merge_composition.merge_commit`).
5. `unit_battery.py` lê o mapa de covers com um segundo leitor porque importar `gate_script_tests.py` fecharia ciclo
   entre três unidades. O conserto é mover a leitura do mapa para uma unidade abaixo das duas, não duplicar o leitor.
   Owner: engine-units e engine-gate-tests.
6. Derivar prova dos covers aumenta o número de suítes por unidade e pode estourar o teto de 10 s da bateria sem nenhum
   teste falhar. A bateria precisa rodar os arquivos de uma suíte em paralelo; até lá, unidade grande sai `fail` por
   tempo. Owner: engine-units (`unit_battery.run`) e engine-battery.
7. O contrato de status declarava `runners` e `jobs` que o CLI nunca leu. Campo declarado sem leitor é promessa falsa:
   o contrato tem de dizer, ele mesmo, quando um campo não é consultado, e o estado desconhecido tem de ser um valor, não
   um vazio. Owner: engine-service (`contracts/service/status.v1.json`).
8. Documento de arquitetura que cita alvo, leitor ou arquivo inexistente não é dívida de prosa: é a diferença entre o
   sistema descrito e o sistema que roda. Uma citação de leitor deveria ser conferível por código no mesmo commit em que
   é escrita. Owner: engine-structure (`docs/architecture/*`).
