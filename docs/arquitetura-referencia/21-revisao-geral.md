# 21. A revisão geral: execução, estruturas, comandos, instruções e a AWS

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Na fronteira de 12:19** ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)): misto. A §1 vira o que o
> executor relata no registro (início e fim de etapa, intervenções, uso), sem colunas escolhidas; na §2, os esquemas
> da infraestrutura são `work` e `log`, e os outros são da gestão; na §3, as entidades da infraestrutura são as de [22
> §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura), e as demais, da gestão ou da liderança; a §4 é toda da
> gestão; na §5, ficam na infraestrutura `tower job`, `log`, `executor`, `limit` e `tenant`; a §6 é da gestão; a §7 é
> da infraestrutura e da instalação; §8 e §9 valem com essas trocas.

O fecho do passo zero (Daniel, 04/11/2026 10:44 BRT: revisar "as estruturas, os comandos, as instruções", e "várias
coisas que terão que ser padronizadas na AWS"). Cada parte é julgada contra a planta de [18](18-planta-geral.md): ela
ajuda a janela de autonomia a crescer, e continua com a mesma forma de 1 PR/min a 1 PR/s? A evidência de hoje vem da
auditoria do passo zero (04/11, sobre o repositório e os 522 eventos do log de 03/11 17:15 a 04/11 12:06 UTC); os caminhos
citados são do repositório.

## 1. A execução

O ciclo de [17](17-ciclo-do-processo.md) fica: as etapas como eventos, o plano como grafo, uma tentativa por processo, a
entrega em ~1 s. A revisão acrescenta quatro coisas que a planta pede:

1. **Toda etapa e todo item têm início e fim.** A tabela de etapas de [17 §5](17-ciclo-do-processo.md#5-o-que-muda-no-modelo-do-16)
   guardava só o fim; sem o início não se mede a duração, e a duração é a medida que o aprendizado mais usa
   ([20 §5](20-sistema-de-aprendizado.md#5-o-que-dá-para-provar-a-1-prmin-e-a-1-prs)).
2. **Toda intervenção é um evento** (`intervention.recorded`, com a classe da parada, quem agiu e quanto tempo o trabalho
   esperou). É o denominador da janela de autonomia; hoje ela só aparece quando alguém abre um incidente à mão.
3. **Toda tentativa registra a versão do padrão** com que rodou ([19 §5](19-direcao-ideal.md#5-o-padrão)).
4. **Toda sessão reporta o que gastou** (`session.usage_reported`: tokens por modelo, tempo, chamadas de ferramenta). Hoje o
   uso por PR é lido de `~/.cache` da máquina que o pede (`flow-metrics --quota`), e o custo em dinheiro por PR não é
   calculado em lugar nenhum.

## 2. As estruturas

| Onde | O que guarda | Por quê |
|---|---|---|
| **git, no Origin** | o código, os contratos, as decisões de Daniel, a intenção, as regras do padrão e as versões candidatas dele | é o estado desejado: muda pouco, pede revisão e história |
| **PostgreSQL, um esquema por subsistema** | `direction`, `work`, `execution`, `verification`, `integration`, `learning`, `pattern` (o registro das versões e das atribuições), `governance` e `events`; pela fronteira, a infraestrutura tem só `work` e `log` ([22 §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura)), e os outros são da gestão | é o estado de execução: transação, índice, consulta; nenhum subsistema escreve no esquema de outro |
| **S3** | artefatos: logs, notas de etapa, provas, os casos de reexecução do aprendizado | grande e barato, com retenção |
| **visões SQL** | a medição: janelas, vazão, guardas, custo | a medição só lê; nada é recalculado a cada leitura numa janela de arquivo |

**O padrão fica em git e muda por PR.** Quando o aprendizado adota uma versão, ele abre a PR que move a versão candidata
para vigente, e a PR passa pela fila como qualquer outra. Assim a regra continua revisável e versionada, e o banco
guarda só qual versão cada tentativa usou.

**O estado de execução sai do git.** Hoje ele está em dois lugares que o modelo não deveria usar para isso:

- **Arquivos commitados:** os incidentes (`scripts/lib/incident.py`), as lições, as 58 premissas e os 3 defeitos, a saída
  de `repeats --write`, as linhas de decisão, a fila `docs/programs/vazao/fila.md` (que `deliver --close-queue` edita), a
  retrospectiva de `program-gate retro --write` e as respostas de `rule --answer`.
- **Branches usadas como estado:** todo evento é anexado a `train/events` (`scripts/lib/forge_git_ref.py`);
  `decision-next --claim` empurra `claude/decision-claims/D-NNN` e nunca a apaga (99 delas vieram do remoto do GitHub); e
  `train/lock`, `train/wake`, `battery/lock`, `tower/test-results` e `plan/live` também são branches
  (`scripts/lib/machine_refs.py`).

No ideal, tudo isso é linha no esquema do subsistema dono, com o número alocado pelo banco e o lease no lugar do lock
([13](13-estado-e-coordenacao.md), [16 §5](16-modelo-de-dominio.md#5-o-modelo-refinado)). O que continua em git é o que
uma pessoa revisaria: o texto de uma decisão, uma regra, um contrato.

## 3. O catálogo das entidades do modelo ideal

Todas as entidades, de todos os subsistemas, com o que o pedido de Daniel pede de cada uma. As relações entre elas estão
no diagrama de [16 §5.3](16-modelo-de-dominio.md#53-relações), na forma revista.

| Entidade | Subsistema | Por que existe | Identidade | Estados | Liga-se a | Quem cria | Quem consome | O que se mede |
|---|---|---|---|---|---|---|---|---|
| Intenção | direção | o porquê | `INT-v<n>` | proposed, validated, superseded | objetivos | Daniel | planejador, medição | a métrica-norte |
| Objetivo | direção | um alvo medido da intenção | `PRG-<slug>` | proposed, active, achieved, abandoned | intenção, apostas | planejador | planejador, aprendizado | métrica de entrada contra alvo; guardas; a classe |
| Aposta | direção | trabalho limitado com efeito esperado | `BET-<n>` | proposed, accepted, active, delivered, evaluated, cancelled | objetivo, processos, escolha | planejador | trabalho, aprendizado | custo contra apetite; efeito |
| Escolha | direção | o julgamento do planejador, auditável | `CH-<n>` | recorded, reviewed | apostas, processos, premissa | planejador | aprendizado | acerto; erro de estimativa |
| Processo | trabalho | o que vira uma PR | `F<n>` | proposed, ready, active, done, failed, cancelled | aposta ou objetivo, plano, tentativas, PR | planejador | trabalho, integração | duração por etapa; intervenções |
| Plano e item | trabalho | a ordem e o caminho crítico dos commits | processo + versão; `n` | proposed, accepted, revised; planned … proven | processo, commits | a tentativa | o workflow do processo | caminho crítico; itens refeitos |
| Etapa | trabalho | o registro de cada passo do METODO | processo + etapa | início e fim | processo, tentativa | a tentativa | aprendizado | duração |
| Tentativa | trabalho | uma execução do processo | processo + `n` | pending … succeeded, failed | sessões, versão do padrão | workflow do processo | trabalho, aprendizado | tentativas por processo |
| Fornecedor e cota | agentes | quem executa, com que limites | o nome; a janela | — | sessões | registro | corretor | cota usada; espera |
| Sessão | agentes | o contexto de execução no fornecedor | fornecedor + id externo | starting, running, idle, ended | tentativa | corretor | trabalho | retomadas sem ninguém; uso |
| Prova e veredito por alvo | verificação | a certeza sem humano | digest do head ou do lote; alvo + digest | queued … completed | PR ou lote | runner | integração | tempo; flake; fuga de seleção |
| PR | integração | o registro no forge | forge + repo + número | draft … merged, closed | processo, lote | sessão e fila | todos | pronta → mergeada |
| Lote e pouso | integração | verificar e pousar em grupo | `b-<12 hex>` | forming … landed | PRs, prova | fila | medição | tamanho; vermelho |
| Sinal | aprendizado | achar o problema sem alguém notar | `SIG-<n>` | detected, explained, dismissed | evidência, lição | workflow de aprendizado | lição | sinais explicados |
| Retrospectiva | aprendizado | o registro de cada processo | o processo | drafted, closed | lições | workflow, com a nota da sessão | lição | cobertura |
| Lição | aprendizado | a explicação com evidência | `LR-<hex>` | recorded, hypothesized, archived | sinal, retrospectiva, hipótese | workflow | hipótese | lições que viram hipótese |
| Hipótese | aprendizado | a mudança com efeito esperado | `H-<n>` | proposed, testing, confirmed, refuted | lições, experimento | analista | experimento | acerto |
| Experimento e veredito | aprendizado | provar com número | `EXP-<n>` | designed, running, stopped; adopted, rejected, inconclusive | hipótese, versão candidata | workflow | padrão, direção | efeito; custo |
| Versão do padrão e regra | padrão | o jeito de fazer, único e atual | `PV-<n>`; id da regra | candidate, current, retired | tentativas, decisões, lições | aprendizado; Daniel | todo agente | tentativas na vigente; contradições zero |
| Pacote de instruções | padrão | o que cada papel recebe | versão + papel | gerado | versão do padrão | gerador | sessões | tamanho em tokens |
| Comando | plataforma | a porta de um subsistema para sessões e pessoas | `tower <subsistema> <verbo>` | — | o subsistema dono, os eventos que emite | PR | sessões, a Torre | uso; erro; sem uso |
| Métrica | medição | uma definição que todos leem igual | o nome | — | eventos | medição | direção, aprendizado | frescor |
| Decisão de Daniel | governança | uma regra, um gasto ou a intenção | `D-NNN` | recorded, proven, superseded | premissas, regras | Daniel | todos | — |
| Premissa | governança | uma suposição com estado | `P-NN` | inferred … refuted | decisões, escolhas | sistema | aprendizado (laço duplo) | refutadas |
| Pedido à Torre | governança | o que só Daniel alcança | `PT-<n>` | open, answered, resolved, declined | processos que destrava | sistema | a Torre | tempo de resposta; bloqueios |
| Intervenção | governança | toda parada que exige alguém de fora | `I-<hex>` | open, closed | processo, classe | sistema | medição, aprendizado | a janela de autonomia |
| Pilha e deploy | plataforma | a infraestrutura como código aplicada | `tower-app-<nome>`; o build | — | commit da base | deployer | todos | deploys verdes; divergência |
| Evento | todos | o registro de toda operação | `event_id` | — (só anexo) | o agregado | o escritor do agregado | todos | atraso |
| Unidade de código | git | a dona dos caminhos | `units/<id>` | — | processos | PR | trabalho, verificação | — |

## 4. A medição

**Uma métrica é uma definição, não um script.** Cada métrica vira uma entrada do catálogo de métricas: o nome, a visão
SQL sobre os eventos que a calcula, o subsistema dono, o alvo ou a guarda e o alarme. Todos leem a mesma definição: o
planejador, o aprendizado, o painel e a Torre. Hoje cada leitura é recalculada pelo script que a pede.

**O que a medição de hoje não alcança.** `flow-metrics` calcula os commits integrados por dia e as razões deles, os
tempos de espera e de autoria, o retrabalho, as PRs por segundo e o degrau da escada, as PRs por minuto de cada hora
fechada, as guardas e o quanto a caixa está ocupada. Não calcula a duração de nenhuma etapa (a única que existe é o p95
de pronta a mergeada no `slo`), nem as intervenções, nem a janela de autonomia, nem o custo em dinheiro por PR. Os 27
incidentes têm tipo, mas nenhum código o lê: `flow-metrics` só conta os abertos.

| Métrica | Calculada de | Para quê |
|---|---|---|
| janela de autonomia (mediana e percentil 10 por dia) | `intervention.recorded` | a métrica-norte proposta ([19 §7](19-direcao-ideal.md#7-a-medição-da-direção)) |
| intervenções por 100 PRs, por classe | `intervention.recorded`, `pr.merged` | qual subsistema atacar |
| PRs por segundo, na janela móvel | `pr.merged` | a capacidade, a escada da semente |
| duração de cada etapa e de cada item | `process.stage_completed`, `plan_item.*` | o aprendizado e o caminho crítico realizado |
| pronta → mergeada | `pr.ready`, `pr.merged` | a entrega em 1 s ([11 §6](11-gate-merge-fila-origin.md#6-metas-numéricas)) |
| custo por PR mergeada | `session.usage_reported`, infraestrutura por tag | a guarda de custo |
| retrabalho, vermelho e flake na fila | `pr.*`, `gate.*` | as guardas de qualidade |
| horas de trabalho pronto na fila | `process.ready` | a saúde da direção |
| tempo de lição a veredito; mudanças adotadas | `lesson.*`, `verdict.recorded` | a saúde do aprendizado |

Cada subsistema tem a sua métrica de saúde ([18 §5](18-planta-geral.md#5-o-contrato-de-cada-parte)) com um
alarme em `tower-alerts`; um alarme que dispara abre uma intervenção só quando pede alguém de fora, e um sinal do
aprendizado sempre.

## 5. Os comandos

**O que existe.** `scripts/` tem 66 executáveis; 58 são invólucros de 5 a 8 linhas que só passam para
`scripts/lib/<nome>.py`, e a lógica de verdade está em oito (`gate-local`, com 413 linhas, `run`, `gate-dev`,
`gate-batch`, `structure-check`, `deliver`, `test-suite` e `gate-verdict`). Por subsistema da planta:

| Subsistema | Hoje | No ideal |
|---|---|---|
| Verificação | 18 comandos (`gate-local`, `gate-dev`, `gate-quiet`, `gate-noite`, `gate-batch`, `gate-shadow`, `gate-verdict`, `battery`, `unit-battery`, `test-suite`, `run`, `prepush`, `commit-check`, `structure-check`, `schema-compat`, `quarantine`, `covers-cost`, `covers-prove`); três dão veredito sobre um head e três rodam a bateria inteira | `tower verify plan\|run\|why`, sobre um head ou um lote; um veredito só, a prova por alvo de [11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s); a bateria inteira é um modo |
| Integração | 8 (`train`, `train-loop`, `deliver`, `pr-ready`, `pr-body`, `plan-tick`, `replay-branch`, `branch-start`) | `tower integrate submit\|status`: a entrega é um evento que o workflow consome, não um script que a sessão roda e espera |
| Direção | 4 (`plan`, `program`, `program-gate`, `coordinator`) | `tower direct`: lê e propõe objetivos, apostas e escolhas; o planejador é workflow ([19 §4](19-direcao-ideal.md#4-o-planejador)) |
| Trabalho e agentes | 8 (`lane`, `lane-status`, `fronts`, `flow-check`, `stall-report`, `usage`, `cycle`, `retro`) | `tower work status\|claim\|release`, sobre o lease do processo |
| Aprendizado e governança | 11 (`lessons`, `premises`, `decision-next`, `decision-record`, `decision-table`, `incident`, `friction`, `defects`, `rule`, `rule-challenge`, `repeats`) | `tower learn` (sinal, lição, hipótese, experimento) e `tower govern` (decisão, premissa, pedido à Torre, intervenção), escrevendo no banco, que aloca o número |
| Medição e eventos | 7 de medição (`flow-metrics`, `commit-rate`, `idea-to-prod`, `slo`, `dashboard`, `budgets`, `checks`) e nenhum para ler os eventos, que pede `scripts/lib/forge_events.py` | `tower measure <métrica>`, lendo o catálogo da seção 4, e `tower events query` |
| Plataforma | 10 (`config`, `units`, `census`, `env-check`, `service`, `generate`, `intake-templates`, `scaffold`, `merge-regenerate`, `operation-relations`) | `tower platform` e `tower config`; os geradores ficam, como etapa do build |

**As regras dos comandos:**

1. Um ponto de entrada, o mesmo local e na nuvem (`scripts/run` já é isso, D-069 item 12), e um verbo por ação.
2. Um comando é um cliente fino do contrato do subsistema ([18 §5](18-planta-geral.md#5-o-contrato-de-cada-parte)):
   ler é consultar uma visão; escrever é mandar um comando ao dono do agregado, que emite o evento. Nenhum comando edita
   um arquivo de estado nem empurra uma branch como estado.
3. Todo comando está no catálogo da planta ([18 §7](18-planta-geral.md#7-a-planta-como-código)) com o subsistema dono e
   os eventos que emite; o teste da planta recusa comando sem dono.
4. O comando que nada chama e nenhum documento cita vira um sinal de aposentadoria do aprendizado
   ([20 §3](20-sistema-de-aprendizado.md#3-o-ciclo-da-evidência-à-mudança-medida)).

**O que sai ou se funde.**

- `gate-quiet` é um apelido de `gate-local`.
- `flow-check` diz que substitui `lane-status`, `service health`, `gate-shadow latest`, `coordinator status` e
  `flow-metrics --cycles`, e os cinco continuam lá.
- Fazem a mesma coisa: `commit-rate` e `flow-metrics --hourly`; `slo show` e `dashboard`; `checks` e `service health`;
  `train serve` e `train-loop`.
- Três coisas geram briefs: `coordinator --briefs`, `lane brief` e `generate lane-briefs`. No ideal, uma: o gerador dos
  pacotes do padrão ([19 §5](19-direcao-ideal.md#5-o-padrão)).
- Não fazem o que o nome diz: `retro` só guarda logs, e nada o chama; `census` nunca escreveu o arquivo dele;
  `coordinator run --apply` lança com uma flag que o documento da lane diz que o CLI não tem.
- `rule-challenge`, `quarantine`, `operation-relations` e `fronts` são citados por um documento cada, e cada um é julgado
  contra a planta antes de ficar.
- Parados: `battery` (desligado no registro), `train` e `train-loop` (até a VM mudar), e `gate-noite` julga a `main`
  congelada.

## 6. As instruções e os prompts

**O que existe.** As instruções estão em sete lugares, escritos à mão e lidos por papéis diferentes em momentos
diferentes:

| Arquivo | Tamanho | O que tem |
|---|---|---|
| `AGENTS.md` | 69 linhas, ~19 KB | 25 regras |
| `CLAUDE.md` | 14 linhas | importa o AGENTS.md |
| `docs/RETOMAR.md` | 135 linhas, ~10 KB | 8 seções |
| `docs/process/lane.md` | 231 linhas, ~23 KB | um contrato de 16 itens e um resumo de 12 |
| `docs/operations/coordinator.md` | 93 linhas, ~10 KB | 9 seções |
| `scripts/lib/coordinator_launch.py` | 136 linhas | o brief, que leva a unidade, todo o padrão v8, as lições aplicadas, as notas do plano e os defeitos |
| `docs/padrao/v8/` | 127 linhas, ~27 KB | 15 regras, 13 citando Daniel |

Somados à SEMENTE e ao METODO, são ~100 KB, na ordem de 25 mil tokens (estimativa: bytes ÷ 4) que uma sessão pode ter de
ler antes de trabalhar. Nenhum teste os confronta com o código nem entre si, e a auditoria achou:

**Sete regras que o código desmente.**

1. O AGENTS.md manda `scripts/gate-dev --pr <n> --why`; o `gate-dev` só lê `--why` como primeiro argumento, e o
   `gate-local` sai com 2 diante dele.
2. A mesma linha do AGENTS.md diz "1-8" e "3–8" itens de plano; o registro (`config/registry/budgets.json`) diz 1 a 8.
3. O AGENTS.md diz que `requeue` e `cancel` controlam o serviço; `scripts/lib/service.py` recusa os dois (D-290).
4. O AGENTS.md diz que o lote está desligado por padrão; `config/registry/delivery.json` tem `auto` como padrão.
5. Três regras do v8 citam `scripts/lib/unit_intake.py`, apagado com a D-292.
6. O v8 manda marcar o plano à mão; o AGENTS.md deriva a marcação dos trailers.
7. O v8 manda "end the turn" depois do gate verde; o AGENTS.md e o gancho `scripts/lib/cycle_stop.py` bloqueiam isso.

**Nove pares de regras que se contradizem, e a que fica no ideal.**

| Tema | Um lado | O outro lado | Fica |
|---|---|---|---|
| comentários na PR | quatro regras do v8 os exigem | o AGENTS.md e o documento da lane os proíbem | nenhum: o registro é o evento e o diário |
| o que só o dono decide | v8: dinheiro, produção, fonte de verdade e escopo | SEMENTE e AGENTS.md: login, credencial, dinheiro e pessoas | a lista fechada da semente, mais a cota, como dado da governança ([19 §6](19-direcao-ideal.md#6-a-governança)) |
| parar | o AGENTS.md manda parar e escalar num conflito de contrato | o AGENTS.md e a SEMENTE proíbem parar por decisão | não parar: o conflito vira sinal e escolha registrada, com o caminho reversível |
| subagente comita | `agent-tree.md`: nunca | `parallelize.md`: comita | um escritor por branch ([17 §3](17-ciclo-do-processo.md#3-o-plano-de-commits-como-dado), [L12]) |
| de onde a faixa tira trabalho | a fila | o grafo do coordenador, um gerente de domínio ou a lane A | a fila de processos prontos, com lease |
| a linha da fila | `fila.md`: a lane apaga a sua | `lane.md`: proibido | ninguém edita a fila: o estado do processo muda por evento ([17 §4](17-ciclo-do-processo.md#4-as-máquinas-de-estado-e-os-eventos)) |
| unidades por lane | `lane.md`: uma | `RETOMAR.md`: duas | a pergunta some: um lease por processo, uma tentativa por vez |
| linhas de decisão | `lane.md`: escrever à mão e reservar o número | `lane.md` mais adiante e o DECISIONS.md: recusadas | o banco aloca o número ([16 §5.2](16-modelo-de-dominio.md#52-identidade)) e a linha é gerada |
| a métrica | `lane.md`: commits | a SEMENTE: PRs por segundo | PRs por segundo, e a janela de autonomia na proposta ([19 §7](19-direcao-ideal.md#7-a-medição-da-direção)) |

**Três envelhecidas.** O documento do coordenador e `docs/padrao/README.md` chamam o padrão de v1, e o vigente é o v8; o
coordenador diz que os arquivos de entrada do v6 são impostos; e cita um `pending.md` que não existe.

**No ideal:**

1. **Uma fonte:** as regras do padrão como dado ([19 §5](19-direcao-ideal.md#5-o-padrão)), cada uma com id, texto, razão,
   papel, etapa, métrica e a suposição que carrega.
2. **Os pacotes por papel são gerados**, nunca escritos: o planejador, o executor do processo, o analista do aprendizado.
   O AGENTS.md e o CLAUDE.md passam a ser o pacote do executor, gerado e com um orçamento de tokens. O brief leva o pacote
   do papel, o contrato do processo e as lições com veredito; nunca o padrão inteiro.
3. **Um teste do padrão**, que pega as três classes acima: todo comando, flag e caminho citado numa regra existe no
   código; cada regra declara o que restringe (a lista de paradas, os comentários na PR, o tamanho do plano), e duas regras
   do mesmo papel e etapa que restringem a mesma coisa com valores diferentes são recusadas; uma regra que cita uma decisão
   superada ou um arquivo apagado é recusada.
4. **Prompts são código:** versionados com o padrão, ligados à tentativa por `pattern_version` e comparados por
   experimento ([20](20-sistema-de-aprendizado.md)).

**O teto do plano sai (Daniel, 04/11 12:37: "Não podemos limitar nossos PRs por causa de burocracia de planejamento").**
A trava está em quatro lugares: o registro `budgets.pr_commits_max` (8), lido por `scripts/lib/commit_check.py`, que
recusa um plano de mais de 8 itens; a linha 42 do AGENTS.md ("1-8" e "3–8"); e três itens do documento da lane. Hoje ela
só avisa, porque o regime de exceção (`regime.exception_active`, desde 01/11) levanta a trava `commit-plan`; quando o
regime acabar, ela volta a recusar. O que precisa mudar: o plano continua obrigatório, com pelo menos um item e cada
commit nomeando o dele, mas sem máximo; o AGENTS.md e a lane dizem isso; e, como `commit_check.py` é arquivo de gate
(D-025), a mudança leva uma decisão com as palavras de Daniel, emendando a D-022 e a D-025. Pela fronteira, é uma regra do
método, da gestão, e nunca da infraestrutura ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)).

## 7. A padronização na AWS

O que já está no bootstrap da #265 vira regra para tudo o que vier:

| Tema | Regra |
|---|---|
| Nomes | `tower-<subsistema>-<coisa>`; as pilhas do deployer são `tower-app-<nome>`; o bootstrap é `tower-bootstrap` |
| Tags | chaves em minúsculas, com o prefixo da organização [B20]: `tower:subsystem`, `tower:stack`, `tower:commit`; o deployer as aplica na pilha, que o CloudFormation propaga aos recursos que aceitam tag, sem repetir em cada modelo; a pilha de rede da #265 usa `project` e `Name` e passa ao prefixo na próxima PR dela |
| Tags de custo | ativar `tower:subsystem` como tag de alocação de custo antes da primeira pilha de aplicação, porque ela só conta depois de ativada e não retroage [B17]; sem dado pessoal em tag, que não é cifrada [B20] |
| Região e conta | us-east-1 e a conta 123456789012, que tem o crédito (a decisão de conta está abaixo) |
| Infraestrutura como código | só CloudFormation em `infra/aws`, aplicado pelo deployer a partir da base; o bootstrap e o orçamento, à mão, fora do alcance do pipeline |
| Identidade | nenhuma chave de longa duração; todo papel com o limite `tower-boundary`; acesso humano pelo IAM Identity Center |
| Segredos | Parameter Store, `/tower/<subsistema>/<nome>`, SecureString com a chave `aws/ssm` |
| Logs e métricas | grupos `/tower/<subsistema>/…` com retenção de 14 a 30 dias; métricas no namespace `Tower/<Subsistema>`; um alarme por guarda, no tópico `tower-alerts` |
| Custo | o teto de US$ 60 no orçamento `torre-motor-teto-60`, sem créditos nem reembolsos; o limite de permissões já impõe o desenho de custo (sem EC2, NAT nem IP elástico; RDS só db.t4g) |
| Ambientes | um só, o de produção da fábrica; testes de infraestrutura em pilhas efêmeras com sufixo, apagadas no fim |

**A conta, uma decisão de Daniel para quando o uso deixar de ser pessoal.** A conta é a fronteira de isolamento, de
cobrança e de cota da AWS [B18], e o Well-Architected separa cargas e ambientes em contas [B21]. Mas ligar o
Organizations nesta conta a torna a conta de gerenciamento, e as SCPs "do not work to restrict any users or roles in the
management account" [B15]; as políticas de tag também pedem o Organizations, e um recurso sem a tag nem aparece como
fora do padrão [B16]. Então, hoje, a regra das tags é imposta pelo teste do repositório, e não por política; e o desenho
de quando o uso deixar de ser pessoal é uma conta de gerenciamento vazia com a carga numa conta-membro, em unidades
organizacionais por função, não por organograma [B19]. Antes disso, é preciso conferir se o crédito do Activate se
divide entre as contas da organização: é dinheiro, então a decisão é de Daniel.

Um teste da #265 já confere parte disso (o limite, os tipos permitidos, a ausência de chave). A regra de nomes e de tags
entra no mesmo teste quando as próximas pilhas chegarem.

## 8. O que o modelo considera e não deveria, e o que não considera e deveria

**Considera e não deveria:**

| O quê | Onde está | Por que sai, e o que fica no lugar |
|---|---|---|
| "cabe no plano gratuito, com folga" como guarda | [SEMENTE](../SEMENTE.md) §4 | contradiz a D-303 (a A1 paga, dentro do crédito e do teto); fica a disciplina de custo como guarda de custo por PR e o teto de US$ 60 |
| commits por dia como métrica | METODO §1, `lane.md` | a métrica é PRs por segundo e, na proposta, a janela de autonomia |
| portfólio e fase como níveis | METODO §1 | [19 §2](19-direcao-ideal.md#2-os-níveis-quais-ficam-e-quais-saem) |
| cinco definições de programa | METODO, padrão v8, o coordenador, `program-gate`, o VAZÃO | uma: o objetivo medido ([19 §1](19-direcao-ideal.md#1-o-que-falha-na-direção-de-hoje)) |
| a lane como dona de unidades | AGENTS.md; o dono `engine-lane` dos 56 manifestos | o lease do processo ([16 §5.5](16-modelo-de-dominio.md#55-regras-que-valem-para-todas-as-entidades)) |
| arquivos de etapa commitados na PR | padrão v8 | eventos com artefato ([17 §6.1](17-ciclo-do-processo.md#61-o-que-falha-hoje)) |
| subagentes em paralelo dentro de uma PR | padrão v8 | uma tentativa por processo ([17 §3](17-ciclo-do-processo.md#3-o-plano-de-commits-como-dado)) |
| o regime de exceção ligado por padrão, que transforma recusas em avisos | o registro `regime.exception_active` | regra imposta; exceção só com dono, prazo e o evento `lock.lifted` |
| estado de execução em git e em arquivos da máquina da sessão | os arquivos e as branches da seção 2, o diário, o livro das lanes, `~/.cache/the-tower` | o banco ([13](13-estado-e-coordenacao.md)) |
| a numeração local de decisões e premissas | `decision_record.py`, `premises.py`, as branches de reserva que nunca se apagam | o banco aloca ([16 §5.2](16-modelo-de-dominio.md#52-identidade)) |
| "intenção" em dois sentidos, "decisão" em dois, `F<n>` em três, "unidade" para quatro coisas | os manifestos, os eventos, os documentos, `deliver.py` | um nome por coisa ([16](16-modelo-de-dominio.md), [19](19-direcao-ideal.md)) |
| instruções escritas à mão em sete lugares, sem teste | seção 6 | os pacotes gerados das regras e o teste do padrão |
| comandos que se repetem, que não fazem o que o nome diz e que nada chama | seção 5 | um comando por verbo, no catálogo da planta |
| a retrospectiva como arquivo escrito à mão e ingerido à mão | `docs/units/*/retro.md`, `scripts/retro` | a retrospectiva montada dos eventos ([20 §4](20-sistema-de-aprendizado.md#4-a-retrospectiva-refeita)) |

**Não considera e deveria:**

| O quê | Por que entra | Onde |
|---|---|---|
| a janela de autonomia, com toda intervenção como evento | é a intenção de origem medida | [19 §7](19-direcao-ideal.md#7-a-medição-da-direção), seção 1 |
| a planta como catálogo testado | o sistema visível e conferível a cada PR | [18 §7](18-planta-geral.md#7-a-planta-como-código) |
| o planejador e a escolha como entidades | saber se o planejador escolhe bem | [19 §3 e §4](19-direcao-ideal.md#4-o-planejador) |
| o padrão com versão, ligado a cada tentativa | comparar versões | [19 §5](19-direcao-ideal.md#5-o-padrão) |
| o efeito medido de cada mudança, de padrão ou de código | aprender com número | [20](20-sistema-de-aprendizado.md) |
| início e fim de cada etapa e de cada item | a duração, a medida mais barata de provar | seção 1 |
| o contexto do agente como recurso, com orçamento por papel | janelas longas acabam quando o contexto acaba | [19 §5](19-direcao-ideal.md#5-o-padrão), seção 6 |
| o orçamento de cada aposta, encaixado no dos processos e das tentativas | o agente gasta o que vê; o delegado não passa o do pai | [19 §3](19-direcao-ideal.md#3-as-entidades-da-direção) |
| o custo por PR por modelo e por subsistema | a guarda de custo com dono | seções 4 e 7 |
| uma métrica de saúde e um alarme por subsistema | cada classe de parada vigiada | seção 4 |
| a suposição que cada regra carrega sobre o que o modelo não faz sozinho | aposentar a regra quando o modelo passa a fazer | [19 §5](19-direcao-ideal.md#5-o-padrão), [20 §2](20-sistema-de-aprendizado.md#2-o-que-o-estado-da-arte-ensina) |

## 9. O teste de escala

| Subsistema | A 1 PR/min | A 1 PR/s | A forma muda? |
|---|---|---|---|
| Direção | uma rodada do planejador a cada ~30 min, dezenas de processos | apostas que geram processos em série, por transformação ([06](06-contrato-planejador.md)) | não; muda quanto cada escolha gera |
| Trabalho e agentes | ~15 sessões simultâneas pelas assinaturas | ~900 com A = 1 ou ~90 com A = 10, pelo adaptador próprio | não; muda o adaptador por classe de processo, que já está na porta |
| Verificação e integração | lote de uma PR, entrega em ~1 s | lotes de até 24, mais partições | não ([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)) |
| Aprendizado | experimentos de dias, efeitos grandes, reexecuções | A/B em horas | não; muda o menor efeito visível por dia |
| Medição e eventos | ~0,3 evento por segundo | ~20 por segundo, partições mensais | não |
| Governança | paradas contadas uma a uma | as mesmas classes, por taxa | não |
| Comandos | ~15 sessões chamando; um script que recalcula do git ou do log ainda responde | ~900 sessões; só a consulta a uma visão responde | não, se os comandos já forem clientes das visões e dos donos (seção 5); é por isso que a regra vale desde já |
| Instruções e prompts | 60 tentativas por hora; ~25 mil tokens de instrução cada são ~1,5 milhão de tokens por hora | 3.600 por hora: ~90 milhões de tokens por hora só de instrução | não; muda o peso do orçamento do pacote, que a 1 PR/s é uma guarda de custo |
