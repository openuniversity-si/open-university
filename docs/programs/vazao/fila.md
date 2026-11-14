# VAZÃO: fila de unidades

Fila do [programa VAZÃO](programa.md), escrita em 03/11/2026 pela lane G (batedora) sobre a base `6f450b00`. Com
várias lanes em paralelo a restrição passa a ser ter unidades concretas, de valor e independentes prontas
([fase 2](fase-2.md)). Esta fila é esse estoque.

A lane P acrescentou F10 a F17 em 03/11/2026 sobre a base `da4b75cab`, em ordem de valor por esforço entre si.
Na reconciliação sobre `e2ba414d`, F10 (#68), F11 (#67), F12 (#69), F13 (#71) e F14 (#72) já estão entregues e
saem da fila ativa. F8 foi entregue em #70 e #73, F9 em #75, F15 em #76, F16 em #78 e #80 e F17 em #79; também
saem. Confira os claims atuais pelo [RETOMAR §2](../../RETOMAR.md#2-onde-estou-cinco-leituras-nesta-ordem).
Os agregados do registro,
`scripts/lib/generated/**` se regeneram no merge (`merge=regenerate` em `.gitattributes`), então duas
linhas que os regeneram não dividem arquivo.

- **O que é:** cada linha é uma unidade pequena, com evidência citável, valor em uma frase e um escopo de arquivos
  disjunto do escopo de todas as outras linhas. Duas lanes que pegam duas linhas não dividem arquivo. Quando uma
  unidade depende de outra, a coluna Escopo diz.
- **Quem tira daqui:** as lanes (subagentes de vida curta, um worktree cada, entrega por `scripts/deliver --branch`).
  A lane A, que é a sessão, atribui a linha à lane. Uma lane pega a primeira linha livre que não depende de outra
  ainda aberta.
- **Como se fecha:** a lane apaga a linha na mesma PR que entrega a unidade. Uma unidade de duas PRs apaga a linha
  na segunda. Ninguém marca "feito" à mão em outro lugar.
- **Ordem:** valor por esforço, do maior para o menor. Tamanho: S (até ~1 h de lane, 1 a 3 commits), M (algumas
  horas), L (o dia ou várias PRs).
- **Fora desta fila:** a divisão de `engine-train` (#55) e de `engine-flow` (#52), a velocidade da suíte (#48, #51,
  #54) e `TOWER_EVENTS_TOKEN` fora do ambiente de teste (lane A). U1/F2 foi descartada e U3/F7 está adiada,
  com os motivos abaixo; nenhuma das duas é estoque disponível.

## Unidades

F16, a última do lote anterior, foi entregue em #78 e #80; do lote seguinte, F19 em #85, F20 em #83, F21 em #90, F23 em #86, F24 em #91, F25 em #88 e F26 em #93, mais F27 (a
trava da caixa cobre também o merge da base e o merge) em #96, F28 em #102, F29 em #101, F30 em #103, F35 em #107, F38 (o medidor da restrição) em #113, F41 em #119, F42 em #117, F47 em #121, F31 em #110, F34 em #116, F43 em #123, F40 em #122, F44 em #128 e #134, F46 em #127, F50 em #143, F52 em #142, F54 em #144, F36 em #126 a #149 (a PR 8 espera F37), F45 em #133, F51 em #148, F53 em #145, F55 em #146, F56 em #147, F57 em #151 e #154, F37 (o Origin exige o gate no head exato: o ruleset `tower-gate-required` ativo em `mod/roadmap-integration`, sem atores de bypass, conferido em 13/11; `aws-pendencias.md` F37) e F63 (a lane encadeia: a regra em lane.md) em #158 e F33 (o relatório de PR/s fora da trava, o push do merge da base sem o pre-push repetido) em #106. F76 (mudar um covers invalida só o próprio teste) sai sem PR própria: TX26 (`b92070863`) já a cumpre, e desde #180, que alargou a seleção, um diff de um só manifesto seleciona o próprio teste, o check do mapa e cada teste cujos covers casam com ele. O lote F18 a F21 vem do [mapa de restrições](sistema.md)
(03/11): a verificação na caixa é a próxima restrição; escopos disjuntos, para lanes em paralelo.

| # | Unidade | Evidência | Valor | Escopo (arquivos) | PRs | Tam. |
|---|---|---|---|---|---|---|
| F97 | **[administração]** (condicional: vale só se alguma lane empurrar de outro container) o gate recusa a PR cuja branch foi empurrada de outro clone, porque o reflog não responde (#213); o gate passa a decidir pela origem da branch no Origin, não pelo reflog local | #213: a PR com branch empurrada de outro clone é recusada pelo gate, e o reflog do clone que entrega não tem a história; hoje toda lane empurra do próprio worktree, então sem uma lane em outro container a linha não tem evidência e fica parada | 0 recusas de PR por reflog ausente | `scripts/lib/forge_origin_history.py`, `scripts/tests/forge_events/test_origin_history.py` | 1 | S |
| F72 | **[capacidade]** (retomada) condicionada a ≥10 entregas com `cpu_s` e caixa ≥70 % ocupada | `flow-metrics --constraint` só aponta a caixa como restrição com ≥10 entregas medindo `cpu_s` (F71) e ocupação ≥70 % | decidir pela medida, não antes | a definir quando a condição valer | 1 | S |

## Deixadas de fora, com o motivo

- **F32 — o custo fixo do gate por PR: descartada em 03/11 pela medida.** Os estágios fixos do gate rodam em paralelo; o
  mais longo é o structure check (12,4 s no #95), e o resto do gate de 50,9 s é teste selecionado (38 s) e ~8 s de
  preparo. A alavanca é quantos testes uma mudança seleciona (covers) e quanto cada um custa (`scripts/tests/costs.json`
  remedido em #108), não os estágios fixos.

- **F18 — testes que falham sob carga: descartada em 03/11.** A falha aparecia com três suítes simultâneas na mesma
  caixa; desde F23 (#86) e F27 (#96) a suíte inteira e o gate esperam a trava da caixa, então essa carga não acontece
  mais. Volta se um gate falhar sem carga com um teste que passa sozinho.

- **F22 — o pre-push roda a seleção do gate: descartada em 03/11.** F19 (#85) mediu que o gate responde pela chave de
  conteúdo tudo o que a suíte da lane já julgou no mesmo head (136 de 136; o gate caiu de 201,8 s para 20,6 s). Rodar a
  seleção antes custa a mesma CPU que deixar o gate rodá-la, e o vermelho custa o mesmo nos dois casos. O que se corta é
  o hábito de rodar a suíte inteira antes de toda entrega: ela só vale quando a mudança mexe em ferramenta compartilhada
  (os furos de seleção, lane.md); numa PR só de documento o gate não seleciona teste nenhum.

- **F2 — local-checks em paralelo (U1 da fase 2): descartada em 03/11.** A medição com threads deu 10,0 s de
  parede contra 8 a 9 s em série (Python preso ao GIL), sem o ganho previsto de ~8 s para ~3 s por push.
- **F7 — sair do regime de exceção (U3 da fase 2): adiada em 03/11, decisão reversível da sessão.** Desligar
  `regime.exception_active` faz o censo de literais voltar a recusar o push, sem ganho demonstrado; os locks de
  estrutura já saíram em #28/#36. Antes de retomar, medir o que o gate passa a recusar e preparar a correção na mesma
  unidade ou sua sucessora. Escopo preservado: `config/registry/regime/regime.exception_active.json`,
  `config/registry/regime.json` e `docs/process/exception-regime.md`.
- **Divisão de `engine-config` (1985), `engine-events` (1846) e `engine-coordinator` (1934).** `json_schema`,
  `python_source`, `config_check` e `event_contracts` são importados por 6 a 13 unidades cada
  (`unit_map.requires` mede os imports estáticos), então mover qualquer um muda o `requires` de muitos manifestos e
  quebra o escopo disjunto. A divisão de `engine-coordinator` esperava uma pergunta: `planner_role.py` saiu de uso
  de fato (F15, 328 linhas a menos); `plan_triage.py` é o `scripts/plan`, que as lanes usam no diário. Depois de F15
  a unidade fica 106 linhas acima do teto, e a medida se refaz.
- **`engine-gate-speed` (1541).** Fica 41 linhas acima do teto; dividir só por isso é inflar. F8 tira dele o
  `forge_rate`, e a medida se refaz depois.
- **Os outros 13 `requires` mútuos.** O grafo de imports entre unidades tem 15 pares mútuos, não 2: F14 tira os dois
  que a divisão de #55 deixou, F12 tira `engine-gate-cache ↔ engine-gate-plan` e F8 tira os dois de `engine-github`.
  Os que sobram ligam `engine-gate-cache`, `-plan`, `-report`, `-speed`, `-tests` e `-ops` entre si, e também
  `engine-config ↔ engine-events`, `engine-commit-plan ↔ engine-push-guard ↔ engine-structure`,
  `engine-defects ↔ engine-gate-report` e `engine-operations ↔ engine-units`. Isso é desenho, não um import solto:
  pede uma auditoria própria (R → A) antes de virar unidade.
- **F114 e F115 — `forge-git-ref.test.sh` e `prepush.test.sh` em paralelo: descartadas em 03/11.** As lanes
  mediram antes (a própria linha mandava medir) e o paralelo não deu o ganho previsto sobre a parede em série (8,3 s e 8,7 s
  em `costs.json`). Voltam se `costs.json` remedido mostrar o teste acima de 8 s e um perfil (`--durations`) mostrar os dois
  módulos de tempo parecido: com um que domina, o piso é ele.
- **F120, F124, F129 e F131 — descartadas em 04/11 pela medida.** F120: o teste leva 1,8 a 3,3 s, não 16 s, e não há espera a
  encurtar. F124: `test_push_guard.py` já monta o repositório uma vez por classe; o tempo está nos pushes e clones de dentro
  dos testes. F129: os `sleep` somam menos de 1 s; o tempo está nas subprocessos (`env.sh`, python de `ou_config_value`).
  F131: o piso de ~3,5 s é a varredura AST de `operation_relations.sites`. Voltam só como unidades sobre essas causas
  (cortar subprocessos do `env.sh`; cache persistente de `operation_relations.sites`), não sobre o arquivo de teste.
- **`gate_bypass`.** `gate-local:100` chama `gate_bypass.py check` em todo gate de PR (0,09 s) e `gate.bypass` é
  `false`, mas é a alavanca da D-151 de Daniel e parte do regime de exceção: sai junto com F7.
- **`structure-check.test.sh`** (`cost 29.9 s`, `share 11.0 s` por PR). Já roda em paralelo e nenhum teste domina (o
  mais lento leva 0,59 s, `unittest --durations`); precisa de um perfil de fixture antes de virar unidade.
- **`retro.test.sh`.** Cada `retro.store` executa o gitleaks de verdade (~0,5 s por teste), mas a suíte só roda em
  16 % das PRs (`share 1.2 s`): pouco valor.
