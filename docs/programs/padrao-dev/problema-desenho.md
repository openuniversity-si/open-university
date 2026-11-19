# PADRAO-DEV — o que vem antes dos requisitos: desenho v5 (salto 1 com S&T)

Para Daniel decidir antes de qualquer implementação. A PR #340 fica em rascunho.

**Retornos de Daniel (19/11):**

- **v1:** completo, com separação explícita, quem cria e quando, e a TOC.
- **v2:** a TOC completa e uma implementação completa.
- **v3:** progressivo; o cenário de uso sai.
- **v4:** a árvore de estratégia e tática (S&T) entra já no salto 1, ao lado do núcleo das cinco perguntas e do
  business case enxuto. O antigo salto 5 sai do roteiro.

**Pesquisas:**

- [problema-pesquisa.md](problema-pesquisa.md): os padrões;
- [problema-pesquisa-toc.md](problema-pesquisa-toc.md) e
  [problema-pesquisa-toc-completa.md](problema-pesquisa-toc-completa.md): a TOC;
- [problema-pesquisa-casos.md](problema-pesquisa-casos.md): o business case e os agentes.

**Critério:** cada salto responde inteiro às perguntas que assume e fecha a 100% no padrão. O salto seguinte só
entra quando seu critério medido se cumpre.

**Quem cria:**

- **Daniel**: decide e aceita;
- **gerente**: a sessão principal;
- **coordenador**: o coordenador de domínio, uma sessão de vida curta;
- **lane**: a sessão da lane;
- **ferramenta**: deriva sem mão.

**Quando:** antes do programa, no desenho, na entrega, depois, ou de forma contínua.

## 1. O salto 1 em uma frase

A Goal Tree diz **o quê** (o estado desejado medido). As leituras e os UDE dizem **onde estamos**. O gap é a
**distância**. A CRT e a nuvem dizem **por quê**. As injeções, com a decisão, dizem **o que fazer e por quê**. A S&T
diz **como**, nível a nível, com dono, até o trabalho.

## 2. Objetos do salto 1

### (a) Estado desejado: a Goal Tree medida

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| INT (existe) | A intenção | — | — | Daniel / antes |
| **NC** | Fator crítico (`csf`) ou condição necessária (`nc`) | statement, level, `target` {comparator, valor ou chave, by?}, `baseline` {value, date, source} | `necessary-for` → INT ou NC; `measured-by` → MEAS | o gerente redige; Daniel aceita os CSF e os alvos / antes |
| MEAS (existe) | A medida e sua fonte | — | — | gerente define; ferramenta lê |

### (b) Estado atual, (c) gap

- **UDE:** statement, evidence e state (observed, gone, returned). Liga-se por `violates` → NC. A ferramenta acusa a
  NC fora do alvo, e o gerente escreve o UDE.
- **Leitura e gap:** derivados pela ferramenta a cada leitura, nunca escritos.

### (d) Problemas

- **CAUSE:** kind (intermediate, root, core), statement e `and_group`. Liga-se por `causes` → CAUSE ou UDE. A
  ferramenta calcula a cobertura da causa central e acusa ciclos. O gerente constrói, e Daniel aceita a causa central.
- **CONFLICT:** a nuvem (a, b, c, d, d′). Liga-se por `objective-is` → NC, por `perpetuates` → CAUSE central e por
  `assumes` → P. O gerente escreve e Daniel aceita.

### (e) Soluções e decisão (com o business case enxuto)

- **INJ:** statement, kind, `effects` (cada um invertendo um UDE), `branches` (ramos negativos), `cost` {tokens, usd,
  wall}, state (candidate, chosen, rejected). Liga-se por `addresses`, `invalidates` → P, `inverts` → UDE e
  `decided-by` → D. Sempre existem as candidatas `do-nothing` e `do-minimum`.
- **D (existe), com `appraisal`:** critérios vindos das NC, datados antes das notas; as opções (INJ); a nota de cada
  uma com evidência; o custo; o porquê da escolha; o caminho de volta. É o núcleo do business case (ISO 21502,
  PRINCE2, Five Case Model). O CASE completo fica para o salto 4.

### (f) Como: a árvore de estratégia e tática

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **ST** | Nó da S&T de Goldratt | level (1 a 4), `strategy` → NC (o estado que o nó deve atingir), `tactic` → INJ escolhida (níveis 1 a 3) ou texto (nível 4), `owner_role`, `validated_by` | `child-of` → ST; `assumes` → P com `role` (necessary, parallel, sufficiency); `decomposes-into` → WORK | por nível, abaixo |
| P (existe) | Premissa | ganha `role` | — | o dono do nó |
| WORK (existe) | Programa ou unidade | — | o programa fica sob um ST de nível 3 e a unidade sob um ST de nível 4, ou herda o do programa | — |

**A S&T não duplica nada:**

- a estratégia de um nó não é texto novo, é uma NC da Goal Tree; o estado do nó é o estado dessa NC (met, not-met);
- a tática é a INJ escolhida, e o porquê dela já está na D e na nuvem;
- as premissas são P;
- a S&T só acrescenta o que nenhum outro objeto tem: **a decomposição do como em níveis com dono, e as três
  premissas que ligam um nível ao outro**. São elas: a necessária (por que este passo é preciso), a paralela (por que
  esta tática e não outra) e a de suficiência (por que os filhos bastam).

**Níveis, donos e quem valida:**

| Nível | O que é na Torre | Dono (redige) | Quem valida | Quando |
|---|---|---|---|---|
| 1 | A intenção: o como da meta inteira | gerente | Daniel | antes, e quando a intenção muda |
| 2 | Os três domínios: capacidade, eficiência, administração | gerente | Daniel | antes de cada ciclo de domínio |
| 3 | Os programas de cada domínio | coordenador do domínio | gerente | no desenho de cada programa |
| 4 | As unidades e as lanes | lane | coordenador | na entrega, ao abrir a unidade |

A ferramenta mede o estado de cada nó pela sua NC e acusa as violações das regras (§4) a cada leitura. A LESSON do
depois revisa as premissas dos nós que não entregaram.

## 3. O conteúdo real da Torre, preenchido (baseline de 19/11/2026)

Tudo aqui é proposta da sessão, a validar por Daniel nos pontos marcados.

### Goal Tree (Daniel aceita os CSF e os alvos)

| Id | Nível | Statement | Medida (fonte) | Baseline | Alvo | Necessária para |
|---|---|---|---|---|---|---|
| NC-throughput | csf | Os PRs mergeados por dia crescem pela escada, sem partir trabalho | merges-per-day em 7 dias | 32,86 | ≥ 1.000 | INT-intention-v1, INT-ladder-1 |
| NC-throughput-2 | csf | Degrau 2 | merges-per-day em 7 dias | 32,86 | ≥ 10.000 | INT-ladder-2 |
| NC-throughput-3 | csf | Degrau 3 | merges-per-day em 7 dias | 32,86 | ≥ 100.000 | INT-ladder-3 |
| NC-quality | csf | Nenhum defeito escapa para a main | escape-rate nas últimas 1.000 merges | 0 | ≤ 0 | INT-intention-v1 |
| NC-autonomy | csf | O fluxo nunca espera Daniel fora da lista fechada | incident-count owner-stop em 7 dias | 1 | ≤ 0 | INT-intention-v1, INT-limits |
| NC-cost | csf | O sistema cabe no que Daniel paga | (as duas abaixo) | — | — | INT-limits |
| NC-aws-spend | nc | AWS abaixo de US$ 200 por mês | aws-spend | 0,00 | ≤ 200 | NC-cost |
| NC-anthropic-spend | nc | Anthropic dentro do orçamento | supplier-spend | 100 | ≤ supply.anthropic_monthly_usd | NC-cost |
| NC-standard | csf | Todo código nasce no padrão e o sistema sabe a verdade sobre si | (as duas abaixo) | — | — | INT-padrao-dev |
| NC-reflexion | nc | Toda dependência entre componentes é permitida | model-share reflexion | 1,0 | ≥ 1,0 | NC-standard |
| NC-requirements-tested | nc | Todo requisito é testado | model-share requirements-tested | 1,0 | ≥ 1,0 | NC-standard |
| NC-ready-supply | nc | Sempre há unidades prontas na fila para as frentes livres | linhas prontas da fila contra frentes livres (MEAS nova, fonte `flow-metrics --constraint`) | 2 linhas, 0 frentes ocupadas | ≥ frentes livres | NC-throughput |
| NC-gate-first-pass | nc | O gate passa na primeira rodada | gate-failure-rate (SLO) | 22,5 % | ≤ 0 % | NC-throughput |
| NC-gate-time | nc | O gate dura no máximo 60 s | run-durations do gate | 119 s | ≤ 60 s | NC-throughput |
| NC-deploy-1s | nc | Uma merge só de código fica no ar em até 1 s | run-durations deploy-live (relógio da D-345) | 1,48 a 2,26 s | ≤ 1 s | NC-throughput |

### UDE (estado atual)

| Id | Statement | Viola | Evidência |
|---|---|---|---|
| UDE-few-merges | A Torre mergeia cerca de 33 PRs por dia, 30 vezes menos que o degrau 1 | NC-throughput | VAL-ladder-1; SLO de merged PRs por hora: 2 contra o mínimo de 42 |
| UDE-idle-flow | Na última hora, 0 merges com a fila parada: a restrição apontada é o "suprimento de unidades prontas" | NC-ready-supply | `flow-metrics --constraint --base origin/main`, 19/11 |
| UDE-gate-red | 22,5 % das rodadas do gate falham | NC-gate-first-pass | SLO gate-failure-rate, 40 amostras |
| UDE-gate-slow | O gate leva 119 s | NC-gate-time | VAL-gate-60s |
| UDE-deploy-slow | O código fica no ar em 1,5 a 2,3 s | NC-deploy-1s | config/validation/runs/deploy-live.json |
| UDE-owner-stop | Uma parada para Daniel em 7 dias | NC-autonomy | VAL-autonomy, docs/operations/incidents/ |
| UDE-blind-constraint | O medidor da restrição ainda lê a base da era Origin: sem `--base` falha, e a ocupação da caixa lê um adaptador Origin | NC-ready-supply | `scripts/flow-metrics --constraint` |

### CRT (a causa central a aceitar por Daniel)

- **CAUSE-request-driven** (core): o fluxo é movido por pedidos, não por um suprimento permanente de trabalho
  pronto. Uma sessão faz o que Daniel ou a Torre pediram e só planeja a próxima unidade quando termina. Leva a:
  - **CAUSE-few-fronts** (intermediária): poucas frentes trabalham ao mesmo tempo. A regra de frentes foi escrita
    para a caixa e o trem da era Origin (parados), e nada abre frentes a partir da fila do GitHub. Isso produz
    UDE-few-merges e UDE-idle-flow.
  - **CAUSE-no-standing-front** (intermediária): nenhum domínio tem uma frente permanente nas condições do throughput
    (gate, deploy, medição). Elas só andam quando alguém pede. Isso produz UDE-gate-red, UDE-gate-slow,
    UDE-deploy-slow e UDE-blind-constraint.
  - **CAUSE-turn-waits** (intermediária): ao terminar o pedido, a sessão tende a encerrar o turno e esperar. Isso
    produz UDE-owner-stop.
- **Cobertura da central:** os 7 UDE de 7.

### Nuvem (o conflito que a perpetua)

- **A** (objetivo, NC-throughput): os PRs mergeados crescem pela escada, sem perder qualidade.
- **B:** Daniel controla o que se constrói (a trava de intenção, SEMENTE §6). Para isso, **D**: as sessões só
  começam trabalho que Daniel ou a Torre pediram.
- **C:** o fluxo nunca para por falta de trabalho. Para isso, **D′**: as sessões geram e começam suas próprias
  unidades o tempo todo.
- D e D′ não convivem.
- Premissa sob B–D (P, to-validate, raio alto): "controlar o que se constrói exige aprovar cada trabalho antes de ele
  começar".

### Injeções e decisão (business case enxuto)

| INJ | O que é | Inverte | Ramos negativos e poda | Custo estimado |
|---|---|---|---|---|
| INJ-do-nothing | Seguir por pedidos | — | o gap continua | 0 |
| INJ-do-minimum | Subir o número de frentes na regra do AGENTS.md | UDE-few-merges (em parte) | frentes sem unidade pronta ficam ociosas; não toca o gate nem a parada | baixo |
| **INJ-tree-governance** (proposta) | Daniel controla pela Goal Tree medida e pelos níveis 1–2 da S&T, que ele valida. Abaixo do nível 2, os coordenadores geram as unidades sob os nós validados de forma contínua, as lanes executam as folhas, e o medidor da restrição passa a ler a fila do GitHub | UDE-few-merges, UDE-idle-flow, UDE-owner-stop, UDE-blind-constraint; abre as frentes permanentes de UDE-gate-red, UDE-gate-slow e UDE-deploy-slow | unidades de pouco valor geradas para encher a fila (podado pelas guardas de split e tangled e porque toda unidade precisa de uma NC de folha); cota estourada com mais frentes (podado por NC-anthropic-spend e pelo teto de 7 frentes) | médio: tokens de coordenadores por ciclo |

A injeção proposta invalida a premissa sob B–D: o controle passa a ser pela árvore medida, não pela aprovação de
cada trabalho.

**Appraisal** (critérios fixados antes das notas):

1. ΔNC-throughput;
2. NC-autonomy;
3. NC-quality;
4. NC-cost.

INJ-tree-governance ganha em 1 e 2, empata em 3 e perde pouco em 4 dentro do teto. A D registra isso e o caminho de
volta.

### S&T da Torre (níveis 1 e 2 para Daniel validar; 3 e 4 como propostas)

| Nó | Nível | Estratégia (NC) | Tática (INJ ou texto) | Premissas (necessária, paralela, suficiência) | Dono / valida |
|---|---|---|---|---|---|
| ST-torre | 1 | NC-throughput (com NC-quality, NC-autonomy, NC-cost como guardas) | INJ-tree-governance | N: 33/dia contra 1.000. P: a governança por árvore mantém o controle de Daniel sem aprovar cada unidade. S: os três domínios juntos cobrem throughput, custo e o próprio sistema | gerente / Daniel |
| ST-capacity | 2 | NC-throughput, por NC-ready-supply, NC-gate-first-pass, NC-gate-time e NC-deploy-1s | Uma frente sempre na restrição que o medidor aponta, e outra na seguinte, assim que ela for conhecida por número | N: a restrição é o suprimento de unidades prontas. P: atacar a restrição rende mais do que o resto (TOC). S: fila pronta, gate rápido e certo, e deploy em 1 s levam ao degrau 1 | gerente / Daniel |
| ST-efficiency | 2 | NC-cost | Cortar o custo por PR mergeado na capacidade atual | N: mais frentes gastam mais cota. P: medir o custo por PR antes de cortar. S: AWS e Anthropic são os dois custos | gerente / Daniel |
| ST-administration | 2 | NC-standard | Manter contratos, medidas e painéis no estado da arte, feitos por ferramenta | N: sem medida confiável, a restrição fica cega (UDE-blind-constraint). P: ferramenta, não mão. S: o modelo a 100 % mais o medidor da restrição na base certa | gerente / Daniel |
| ST-capacity-1000 | 3 | NC-ready-supply | Programa reach-1000-prs-per-day | — | coordenador de capacidade / gerente |
| ST-gate | 3 | NC-gate-first-pass, NC-gate-time | Programas gate-speed e gate-excellence | — | coordenador de capacidade / gerente |
| ST-deploy | 3 | NC-deploy-1s | A troca de código abaixo de 1 s | — | coordenador de capacidade / gerente |
| ST-constraint-meter | 3 | NC-ready-supply | `flow-metrics --constraint` lê a fila e as rodadas do GitHub | — | coordenador de administração / gerente |
| ST-padrao | 3 | NC-standard | Programa padrao-dev | — | coordenador de administração / gerente |
| (nível 4) | 4 | a NC do pai ou uma filha | cada unidade da fila | — | lane / coordenador |

## 4. Regras do sistema de gestão (salto 1)

**Estado desejado e estado atual:**

1. Uma INT é coberta por um CSF.
2. Uma NC tem MEAS, alvo e baseline. Uma medida sem fonte não conforma.
3. Uma NC fora do alvo tem um UDE.
4. Um UDE viola uma NC e tem uma CAUSE.

**Problemas:**

5. A CRT não tem ciclo. A causa central tem cobertura medida e um CONFLICT.

**Soluções e decisão:**

6. A causa central tem INJ candidatas, entre elas do-nothing e do-minimum.
7. Uma INJ escolhida tem uma D com `appraisal` (critérios vindos de NC, datados antes das notas) e não tem ramo
   negativo aberto.
8. Uma NEED deriva de uma INJ escolhida e serve a uma NC.

**S&T:**

9. Um ST tem a estratégia numa NC.
10. A estratégia de um ST filho é a NC do pai ou uma descendente dela pela Goal Tree. É a necessidade lida da Goal
    Tree, nunca escrita de novo.
11. Um ST dos níveis 1 a 3 tem como tática uma INJ escolhida. Todo ST tem as três premissas, e uma P refutada reabre o
    nó.
12. Todo ST tem dono e validação do seu nível (§2(f)). Sem a validação, o nó fica `proposed` e não conforma.
13. Toda INJ escolhida é a tática de algum ST.
14. Todo programa ativo fica sob um ST de nível 3. Toda unidade fica sob um ST de nível 4 ou herda o do seu programa:
    nenhum trabalho órfão.
15. O estado de um ST é o estado da sua NC, derivado.

## 5. O que o salto 1 entrega (uma PR, em commits)

1. Uma D que substitui a D-347.
2. O sistema de gestão `problem`, com os tipos NC, UDE, CAUSE, CONFLICT, INJ e ST, os campos novos de D (`appraisal`)
   e de P (`role`), os contratos, os tipos gerados, as regras 1 a 15 e os testes.
3. A MEAS nova de NC-ready-supply e o medidor da restrição na base do GitHub (corrige UDE-blind-constraint).
4. O conteúdo da §3: a Goal Tree, os UDE, a CRT, a nuvem, as INJ, a D e a S&T. Os níveis 1 e 2 entram já validados
   pelo sim de Daniel a esta proposta, e os níveis 3 e 4 com a validação do gerente e do coordenador.
5. A migração:
   - as NEED que diziam objetivo viram NC;
   - as VAL delas passam a ser a leitura das NC;
   - o PROB/OBJ do v1 sai;
   - cada programa ativo e cada unidade da fila ganha o seu ST.

O fechamento é o sistema `problem` a 100 % no `measure` e o modelo com 0 erros e 0 avisos. A engenharia não é
reaberta.

## 6. Roteiro dos saltos seguintes

| Salto | O que entra | Quando passa a valer (critério medido) |
|---|---|---|
| 2. Prova da lógica | RESERVATION (reservas de um revisor independente; uma aberta bloqueia a D) e EXP (experimentos sobre P e INJ) | quando o salto 1 fechar a primeira volta, ou antes, se uma INJ escolhida ou um ST depender de uma P de alto raio não confirmada. A premissa sob B–D já é dessa classe, então este salto é provavelmente o próximo |
| 3. Controle do fluxo | CONSTRAINT, POLICY (a corda de frentes derivada da restrição), BUFFER, full kit, T/I/OE | quando NC-throughput ficar not-met por duas leituras seguidas com a mesma restrição apontada pelo medidor (corrigido no salto 1) |
| 4. Business case completo e throughput accounting | O CASE de cinco dimensões por programa, e a regra ΔT > ΔI > ΔOE | quando duas INJ disputarem a mesma cota ou o mesmo teto, ou quando um programa passar do seu apetite |
| Roteiro futuro | SCEN (cenário de uso), a camada de mercado, o valor monetário de T, o DBR slot a slot | o SCEN, quando uma solução tiver atores externos; os outros, se a Torre vender ou agendar uma máquina |
