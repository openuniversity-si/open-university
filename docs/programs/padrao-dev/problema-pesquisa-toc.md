# Thinking Processes da TOC antes dos requisitos: estado atual, estado desejado, problemas, soluções

Complementa `research-before-requirements.md` (15288 6.4.1, 29148, INCOSE NRM, BABOK v3, ISO 21502).
Pergunta: como os Thinking Processes (TP) de Goldratt, e a versão de Dettmer (Logical Thinking Process, LTP),
separam estado atual, estado desejado, problemas e soluções, e que modelo de referência completo sai disso.

## 0. Resposta curta

- Os TP respondem a três perguntas em sequência: **o que mudar?** (CRT, cloud), **para o que mudar?**
  (cloud com injeções, FRT), **como causar a mudança?** (PRT, TT; depois S&T). Goldratt, *It's Not Luck* (1994);
  Kim, Mabin & Davies 2008.
- Dettmer (LTP, 2007) põe o **Goal Tree** (antes "IO Map") **primeiro**: ele é o estado desejado e o padrão contra
  o qual se mede o desvio. Um UDE só é UDE **em relação ao goal/necessary conditions** (definição TOCICO).
  Então: estado desejado (Goal Tree) -> estado atual (CRT, cujos UDEs são os desvios do Goal Tree) -> conflito
  que mantém o problema (cloud) -> solução validada (FRT + NBR) -> obstáculos e passos (PRT, TT).
- O que a TOC tem que os padrões não têm: **lógica causal verificável** (CLR) dos sintomas ao núcleo, o
  **conflito como razão de o problema persistir**, **injeções testadas contra seus efeitos colaterais** (NBR)
  e **obstáculos explícitos** antes do plano. O que os padrões têm que a TOC não tem: **medidas com baseline e
  alvo**, **need != requirement**, **realização de benefício** fechando o laço. O modelo proposto (§5) junta os dois.

## 1. Fontes

| # | Fonte | Uso aqui |
|---|---|---|
| T1 | Goldratt, *It's Not Luck* (North River, 1994) | Primeira apresentação dos TP completos (CRT, EC, FRT, PRT, TT) e das três perguntas. (conhecimento do livro) |
| T2 | Goldratt, *The Goal* (1984; 3ª ed. 2004) | Cinco passos de foco; "o que mudar/para o que/como" aparece no epílogo. (conhecimento do livro) |
| T3 | Kim, Mabin & Davies, "The theory of constraints thinking processes: retrospect and prospect", IJOPM 28(2):155–184, 2008, doi:10.1108/01443570810846883 ([Emerald](https://www.emerald.com/insight/content/doi/10.1108/01443570810846883/full/html)) | Revisão acadêmica 1994–2006 dos TP; aplicações, métodos, lacunas (pouca validação empírica, ferramentas usadas isoladamente). |
| T4 | Dettmer, *Goldratt's Theory of Constraints: A Systems Approach to Continuous Improvement* (ASQ, 1997) | Definição canônica das cinco árvores e das CLR. (conhecimento do livro) |
| T5 | Dettmer, *The Logical Thinking Process: A Systems Approach to Complex Problem Solving* (ASQ, 2007) ([Goodreads](https://goodreads.com/book/show/2147388.The_Logical_Thinking_Process_A_Systems_Approach_to_Complex_Problem_Solving)) | IO Map/Goal Tree primeiro; CRT como gap contra o Goal Tree; ordem Goal Tree -> CRT -> EC -> FRT -> PRT -> TT. Rename IO Map -> Goal Tree e uso como primeiro passo: [Focus and Leverage, Goal Tree pt.1](https://focusandleverage.blogspot.com/2021/02/the-goal-tree-part-1.html), [part 24](https://focusandleverage.blogspot.com/2019/06/new-book-part-24.html). |
| T6 | Cox & Schleier (eds.), *Theory of Constraints Handbook* (McGraw-Hill, 2010), cap. 23 "The TOC Thinking Processes" ([toc-goldratt](https://www.toc-goldratt.com/en/product/the-toc-thinking-processes-chapter-23-of-the-theory-of-constraints-handbook)) | Estado do corpo de conhecimento: three-cloud, S&T, CLR. |
| T7 | Cox, Boyd, Sullivan, Reid, Cartier, *The TOCICO Dictionary* (2ª ed. 2012) — entradas via espelho ([CRT](https://bipulse.ru/app/dictionary/docs/current_reality_tree), [UDE](https://bipulse.ru/app/dictionary/docs/undesirable%20effect), [core problem](https://bipulse.ru/app/dictionary/docs/core%20problem), [three-cloud](https://bipulse.ru/app/dictionary/docs/three-cloud_approach), [S&T](https://bipulse.ru/app/dictionary/docs/strategy%20and%20tactics%20tree)) | Definições: CRT = diagrama de suficiência que responde "o que mudar?"; UDE = aspecto negativo da realidade **definido em relação ao goal ou às necessary conditions**; core problem em quatro níveis, o mais baixo sendo **uma premissa errada que impede quebrar o core conflict**. |
| T8 | TOCICO learning center ([TP certification review](https://learningcenter.tocico.org/courses/certification-review-thinking-processes); [S&T pt.1](https://learningcenter.tocico.org/courses/strategy-and-tactics-trees-part-1)); TOCICO 2007 deck ([pdf](https://www.tocico.org/_files/ugd/af4d5f_83557c13f5904f6381b8b416d7bacb71.pdf)) | CRT de 6–10 UDEs por "por quê" com CLR; parar quando "o que mudar" estiver achado. |
| T9 | Goldratt, R. Goldratt, Abramov, "Strategy and Tactics" ([WSU mirror](https://public.wsu.edu/~engrmgmt/holt/em534/Goldratt/Strategic-Tactic.html)) | S&T: cada nó = strategy, tactic, necessary/parallel/sufficiency assumptions. |
| T10 | Scheinkopf, *Thinking for a Change: Putting the TOC Thinking Processes to Use* (St. Lucie, 1999) | Uso prático; "UDE cloud" e cloud como ferramenta de comunicação. (conhecimento do livro) |
| T11 | dbrmfg.co.nz, guia de TOC ([CRT construction](https://www.dbrmfg.co.nz/Thinking%20Process%20CRT%20Construction.htm), [3-cloud](https://www.dbrmfg.co.nz/Thinking%20Process%20CCRT%203%20Cloud.htm)) | Prática: three-cloud é socrático/consenso, não substitui o rigor do CRT. |

Limite: livros de Goldratt/Dettmer/Cox não foram relidos nesta sessão (pagos); Wikipedia e Flying Logic estão fora
da rede da sessão. Definições TOCICO vêm de um espelho; conferir no dicionário oficial antes de citar formalmente.

## 2. As três perguntas e as ferramentas

| Pergunta | Ferramenta(s) | Saída | Lógica |
|---|---|---|---|
| (0, Dettmer) Qual é o sistema e o que é sucesso? | **Goal Tree / IO Map** | Goal, 3–5 CSFs, necessary conditions (NC) | necessidade ("para ter A, preciso de B") |
| 1. O que mudar? | **CRT**; **EC** do core conflict (ou **three-cloud**) | UDEs ligados ao core problem/core driver; core conflict e suas premissas | suficiência ("se A [e B], então C") no CRT; necessidade no EC |
| 2. Para o que mudar? | **EC** (injeções que quebram premissas) -> **FRT** com **NBR** | Injeções; desired effects (DE) = UDEs invertidos; ramos negativos podados | suficiência |
| 3. Como causar a mudança? | **PRT** (obstáculos -> IOs); **TT** (ações passo a passo); **S&T** (desdobramento organizacional) | Plano sequenciado com razão de cada passo | necessidade (PRT); suficiência (TT, S&T) |
| Verificação de toda árvore | **CLR** | Árvore escrutinada | 8 regras (§3.7) |

Kim, Mabin & Davies (T3) e o próprio Goldratt notam que as ferramentas também são usadas isoladamente (ex. só a cloud);
a cadeia completa é o uso "sistema".

## 3. Cada ferramenta: propósito, entidades, entradas/saídas, lógica

### 3.1 Goal Tree / Intermediate Objectives Map (Dettmer, T5)
- **Propósito**: definir o estado desejado do sistema inteiro, como padrão contra o qual se mede o desvio.
- **Entidades**: **Goal** (1, o resultado final; nas empresas, definido pelo dono do sistema); **Critical Success
  Factors** (3–5, resultados terminais que juntos garantem o goal); **Necessary Conditions** (até ~3 níveis abaixo,
  efeitos/ações que cada CSF exige). Opcional: medida por CSF/NC.
- **Lógica**: necessidade, de baixo para cima ("para ter CSF, é preciso NC"). Sem "nice-to-have".
- **Entrada**: dono do sistema, fronteira e controle (span of control vs. sphere of influence, Dettmer).
- **Saída**: o padrão. Cada NC não atendida na realidade é candidata a UDE (o gap).

### 3.2 Current Reality Tree (T1, T4, T7)
- **Propósito**: explicar por que o sistema está onde está; achar a pouca coisa que causa a maioria dos UDEs.
- **Entidades**: **UDE** (sintoma negativo, observável, relativo ao goal/NC; 6–10 de áreas diversas, T8);
  **entidades intermediárias** (fatos da realidade); **root causes** (entradas sem causa no diagrama);
  **core problem / core driver** (root cause que leva a ~70% ou mais dos UDEs, convenção de Goldratt/Dettmer);
  **elipses AND** (causas conjuntamente suficientes); **loops** de reforço negativo.
- **Lógica**: suficiência, "se ... então ...", de baixo (causas) para cima (UDEs).
- **Regra**: pare quando "o que mudar" estiver identificado (T8). O core problem tem quatro níveis; o mais
  profundo é uma premissa errada que trava o core conflict (T7) — por isso CRT e EC se encaixam.

### 3.3 Evaporating Cloud / Conflict Resolution Diagram (T1, T4)
- **Propósito**: expor o conflito que faz o problema persistir (se a solução fosse óbvia e sem conflito, já teria
  sido feita) e quebrá-lo sem compromisso.
- **Entidades** (5 caixas): **A objective** (comum); **B, C requirements** (necessidades que A exige);
  **D, D' prerequisites** (ações/condições em conflito, D para B, D' para C); **conflito** D <-> D';
  **assumptions** sob cada seta (A-B, A-C, B-D, C-D', D-D'); **injection** = condição/ação que torna uma premissa
  inválida e evapora o conflito.
- **Lógica**: necessidade ("para ter B, preciso de D porque [premissa]").
- **Variantes**: **UDE cloud** (cada UDE é a consequência de viver um lado de um dilema crônico, T10);
  **three-cloud** (três UDEs independentes -> três clouds -> uma **core conflict cloud** generalizada, T6/T7);
  críticos dizem que pode não chegar ao core problem; T11: bom para consenso, não substitui o rigor do CRT.

### 3.4 Future Reality Tree (T1, T4)
- **Propósito**: provar, antes de agir, que as injeções produzem o estado desejado e nada pior.
- **Entidades**: **injections** (entradas, condições futuras, não ainda reais); entidades intermediárias;
  **Desired Effects** (normalmente cada UDE invertido); **Negative Branch Reservation (NBR)** = ramo que mostra
  um efeito novo indesejado causado pela injeção, aparado com uma injeção adicional; **loops positivos**
  (auto-sustentação).
- **Lógica**: suficiência. Saída: o conjunto de injeções suficiente e o estado futuro descrito como efeitos.

### 3.5 Prerequisite Tree (T1, T4)
- **Propósito**: tornar a injeção ambiciosa implementável quando o caminho não é óbvio.
- **Entidades**: **ambitious target / injection** (topo); **obstacles** (por que não dá hoje, levantados pelo grupo);
  **intermediate objectives (IO)** (condição que supera cada obstáculo); ordem de dependência entre IOs.
- **Lógica**: necessidade. (O IO Map de Dettmer é uma PRT sem obstáculos, T5.)

### 3.6 Transition Tree (T1, T4)
- **Propósito**: ações concretas e sequenciadas para atingir cada IO, com a razão de cada ação.
- **Entidades** (versão 5 entidades de Goldratt, ~2002): **need** (por que agir), **action**, **expected effect**,
  **premise/reality** (fato que faz a ação funcionar), e o efeito anterior. Versão Dettmer: ação + condição
  existente -> efeito -> próxima ação.
- **Lógica**: suficiência. É o plano executável; aqui o TP encontra a gestão de projeto.

### 3.7 Categories of Legitimate Reservation (T4)
Regras para escrutinar qualquer árvore (oito): **clarity** (está claro?); **entity existence** (a entidade é real e
bem formada?); **causality existence** (a seta existe?); **cause insufficiency** (falta um "e" para a causa
bastar?); **additional cause** (há outra causa independente do mesmo efeito? ela muda a magnitude?);
**cause-effect reversal** (a seta está ao contrário?); **predicted effect existence** (se a causa é real, que
outro efeito deveria existir — e existe?); **tautology** (efeito usado como prova da causa).
São o mecanismo de validação da TOC: uma entidade causal sem passar pelas CLR é opinião.

### 3.8 Strategy & Tactics Tree (T6, T9)
- **Propósito**: desdobrar um objetivo ambicioso ("viable vision") em níveis de estratégia (o quê) e tática (como),
  com premissas explícitas, para toda a organização.
- **Entidades por nó**: strategy; tactic; **necessary assumption** (por que a estratégia é necessária); **parallel
  assumption** (por que esta tática, objeções laterais); **sufficiency assumption** (por que as táticas filhas bastam).
- Relevância: é o equivalente TOC de uma decomposição de programa/projeto com rationale por nó; substitui PRT/TT
  em escala organizacional. Útil para um programa multi-nível (programa -> projeto -> PR).

## 4. Ordem do LTP (Dettmer, T5)

1. **Goal Tree** — goal, CSFs, NCs (estado desejado; o dono do sistema valida).
2. **CRT** — UDEs = NCs/CSFs não satisfeitos hoje (o gap), ligados por suficiência à(s) root cause(s).
3. **EC** — o conflito que impede eliminar a root cause; premissas; injeções.
4. **FRT** — injeções -> desired effects (as NCs atendidas); NBR podados.
5. **PRT** — obstáculos -> IOs.
6. **TT** — ações.
Gap = Goal Tree (dever ser) vs. CRT (é). Na TOC clássica o gap é qualitativo (entidades); Dettmer não exige medida
numérica por NC. Essa é a lacuna que os padrões (§1 do estudo anterior) preenchem.

## 5. Comparação com os padrões e mapeamento

### 5.1 Onde a TOC é mais forte
- **Causalidade verificável**: sintomas -> root cause por suficiência e CLR; 15288/NRM/BABOK tratam root cause como
  técnica opcional, sem regra de validade.
- **Conflito como razão de persistência**: nenhum padrão modela "por que ainda não foi resolvido"; a cloud e suas
  premissas explicam e geram a injeção.
- **Solução validada antes de agir**: FRT prova suficiência das injeções; **NBR** é análise de risco estruturada
  (efeito colateral causal, não matriz de probabilidade).
- **Obstáculos explícitos** (PRT) antes do plano; **premissas por passo** (TT, S&T).
- **Foco**: o core problem é um só (alavanca), alinhado com o constraint.

### 5.2 Onde os padrões são mais fortes
- **Medidas**: MOE/MOP/KPI com baseline, alvo e prazo (NRM §4.3.2, BABOK 6.1/6.2, OKR). TOC tem medidas
  operacionais (T, I, OE) mas o Goal Tree não exige medida.
- **Need vs requirement** e **ConOps** (15288 6.4.2, 29148, NRM): TOC para na ação; não gera requisitos verificáveis.
- **Alternativas e decisão formal** (solution classes, business case, decision mgmt 6.3.3): TOC tende a uma injeção
  "certa" e não registra alternativas rejeitadas.
- **Experimento** (Lean Startup/Cynefin, assumption tests): FRT é prova lógica, não empírica; T3 aponta pouca validação.
- **Benefit realization** (ISO 21502 §7.3, BABOK cap. 8): TOC não tem objeto de "o UDE sumiu de fato, medido".

### 5.3 Mapeamento TP -> modelo anterior

| Entidade TP | Objeto anterior | Observação |
|---|---|---|
| Goal | MGO (goal) / INT | O goal do sistema; acima dele só a intenção |
| CSF, NC | MGO/OBJ (objetivos) + MEASURE | TOC não mede; o modelo exige medida |
| UDE | PROB + STATE(current) | UDE = sintoma observado relativo a NC |
| entidade intermediária, root cause, core problem | CAUSE | CAUSE vira grafo, não campo texto |
| core conflict (EC) + assumptions | (ausente) CONFLICT + premissa (P-NN) | novo |
| injection | OPT | candidata; escolhida via DECISION |
| desired effect | STATE(future) / OBJ target | DE = NC atendida |
| NBR | risco de OPT (ausente como objeto) | novo |
| (ausente) | EXP | TOC não tem; FRT é o "teste lógico", EXP o empírico |
| (ausente) | DECISION | TOC implícita |
| obstacle, IO (PRT) | (ausente) OBSTACLE, IO | ponte para CONCEPT/NEED e plano |
| action (TT), S&T node | plano/unidades do programa | a fila de unidades |
| (ausente) | CONCEPT, NEED, REQ | padrões |
| (ausente) | BENEFIT | padrões; fecha o laço no Goal Tree |

## 6. Modelo de referência completo

Convenções: `who` = **owner** (Daniel; decide e valida), **session** (agente que analisa e propõe),
**tool** (derivado automaticamente de medidas/registros). `when` = **pre** (antes do programa), **design**
(desenho do programa), **delivery**, **post** (depois da entrega). Toda entidade causal passa por CLR
(campo `clr` com veredito e quem escrutinou). Elementos mantidos ou adiados justificados por adequação a um padrão
de elite, não por custo.

### (a) Estado desejado
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **INT** (existe) | Intenção; fronteira superior | statement, validator | — | owner / pre |
| **GOAL** | Goal do sistema (Goal Tree topo) | statement, system boundary, span_of_control | `serves` -> INT | owner valida, session redige / pre |
| **CSF** | Fator crítico (3–5) | statement, terminal outcome | `necessary_for` -> GOAL | session propõe, owner aceita / pre |
| **NC** | Necessary condition | statement, level | `necessary_for` -> CSF/NC | session / pre–design |
| **MEASURE** | Medida de CSF/NC (MOE) | metric, unit, source (comando), direction, target{value, by} | `measures` -> CSF/NC | session define, owner aprova alvo / pre |
Mantido inteiro: Goal Tree sem medida é não falsificável; medida sem Goal Tree perde a lógica de necessidade.

### (b) Estado atual
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **READING** | Leitura de MEASURE | value, at, source_ref | `reads` -> MEASURE | **tool** (flow-metrics etc.) / contínuo |
| **BASELINE** | Leitura de referência congelada | reading ref, window, rationale | `baseline_of` -> MEASURE | tool calcula, session fixa / pre |
| **UDE** | Sintoma negativo observado | statement (presente, factual), evidence[] (readings, incidentes, frictions), magnitude | `violates` -> NC/CSF; `observed_in` -> READING | tool detecta (medida fora do alvo), session redige; UDE qualitativo: session/owner / pre, delivery |
Regra (TOCICO): UDE sem `violates` não é UDE.

### (c) Gap
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **GAP** | Distância por medida | measure, baseline, target, delta, trend | `of` -> MEASURE; `evidences` -> UDE | **tool** (derivado, nunca à mão) / contínuo |
Derivado e não armazenado como verdade: recalculado a cada READING.

### (d) Problemas
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **CAUSE** | Entidade do CRT (intermediária ou root) | statement, kind (intermediate|root|core), coverage (% UDEs alcançados), clr{verdict, by} | `causes` -> CAUSE/UDE (com `and_group`); | session constrói, tool calcula coverage e checa ciclos / design |
| **CORE** (CAUSE kind=core) | Core problem/driver | — | `explains` -> GAP[] | session propõe, owner aceita / design |
| **CONFLICT** | Core conflict (EC) | objective A, requirements B/C, prerequisites D/D' | `perpetuates` -> CORE; `objective_is` -> CSF | session (CRT ou three-cloud), owner revisa / design |
| **ASSUMPTION** | Premissa sob uma seta (reusa P-NN) | statement, arrow (A-B, B-D, D-D'…), status (unconfirmed|confirmed|refuted) | `underlies` -> CONFLICT/CAUSE link | session; EXP confirma/refuta / design, delivery |
Mantido: o conflito é a razão do problema persistir; sem ele a injeção é chute. Core sem coverage é palpite.

### (e) Soluções
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **INJ** (OPT) | Injeção candidata | statement (condição futura), kind (policy|mechanism|measure), alternatives considered | `invalidates` -> ASSUMPTION; `addresses` -> CORE | session gera várias, incluindo "não fazer" / design |
| **FRT link** / **DE** | Efeito desejado | statement = UDE invertido | `inverts` -> UDE; `predicts` -> READING esperada em MEASURE | session; tool checa que todo UDE tem DE / design |
| **NBR** | Ramo negativo (risco) | effect, causal chain, severity, trimming INJ | `caused_by` -> INJ; `trimmed_by` -> INJ | session; owner aceita risco residual / design |
| **EXP** | Teste empírico de premissa/injeção | hypothesis, method, success criterion (em MEASURE), result | `tests` -> ASSUMPTION/INJ; `confirms`/`refutes` | session desenha e roda; tool lê resultado / design, delivery |
| **DECISION** (D-NNN) | Escolha | chosen INJ set, rejected + why, residual NBRs, revert path | `selects` -> INJ; `justified_by` -> GAP, EXP | owner (ou session pela regra D-294, registrando reversão) / design |
Mantido inteiro: FRT dá prova lógica, EXP prova empírica, NBR o risco; nenhum padrão sozinho cobre os três.

### (f) Transição
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **OBSTACLE** | Por que a injeção não acontece hoje | statement | `blocks` -> INJ | session (owner contribui) / design |
| **IO** | Objetivo intermediário que supera obstáculo | statement, order | `overcomes` -> OBSTACLE; `precedes` -> IO | session / design |
| **CONCEPT** | Como a solução escolhida opera | scenarios, actors | `realizes` -> DECISION | session / design |
| **NEED** (existe) | Necessidade de stakeholder sobre a solução | (existente) | `derived_from` -> IO/CONCEPT; `serves` -> NC | session / design |
| **REQ** ... VAL (existe) | — | — | — | — / delivery |
| **ACTION/unit** (TT ou S&T) | Passo executável (unidade/PR) | need, action, expected effect, premise | `achieves` -> IO; `implements` -> REQ | session / delivery |
S&T adiado como objeto distinto: TT + IO cobrem um programa; adotar S&T quando o programa tiver >2 níveis de
desdobramento com donos distintos (o nó S&T é IO + premissas, já representável).

### (g) Laço de benefício
| Objeto | Propósito | Campos | Links | Who / when |
|---|---|---|---|---|
| **BENEFIT** | O gap fechou? | reading after, vs baseline/target, verdict (met|partial|not_met|worse), attribution | `measures` -> MEASURE; `confirms` -> DE; `closes`/`reopens` -> UDE | **tool** lê, session atribui, owner aceita veredito / post |
| **RETRO** | O que a lógica previu vs. o que aconteceu | refuted assumptions, unseen NBR, new UDEs | `revises` -> CAUSE/ASSUMPTION/GOAL | session / post |
Fecha: BENEFIT prova DE -> NC -> CSF -> GOAL. VAL prova NEED; VER prova REQ; BENEFIT prova o Goal Tree.

### 6.1 Derivável por ferramenta vs. juízo humano
- **Tool**: READING, BASELINE (cálculo), GAP, UDE quantitativo (medida fora do alvo), coverage do CORE, checagens de
  grafo (UDE sem `violates`, UDE sem DE, INJ sem DECISION, NBR sem trimming/aceite, DECISION sem EXP quando há
  ASSUMPTION unconfirmed de alto raio, NEED sem `serves` NC, MEASURE sem BENEFIT após entrega), ciclos e CLR
  formais (tautologia: efeito citado como evidência da própria causa; entidade sem evidência).
- **Session (juízo)**: CRT causal, CONFLICT, INJ, NBR, EXP, OBSTACLE/IO, CLR substantivas.
- **Owner**: GOAL, aceitação de CSF e alvos, aceitação do CORE e risco residual, veredito de BENEFIT que muda a intenção.

### 6.2 Fluxo
pre: INT -> GOAL/CSF/NC/MEASURE -> BASELINE -> UDE -> GAP.
design: CRT (CAUSE, CORE) -> CONFLICT/ASSUMPTION -> INJ -> FRT (DE, NBR) -> EXP -> DECISION -> OBSTACLE/IO -> CONCEPT -> NEED -> REQ.
delivery: ACTION/units -> VER/VAL; EXP em andamento; READINGs contínuas.
post: BENEFIT -> RETRO -> volta ao Goal Tree (novo UDE, nova iteração do POOGI).

### 6.3 Adiado (com razão de adequação)
- **Throughput accounting (T, I, OE)** como medidas obrigatórias: são do domínio financeiro; o Goal Tree já admite
  qualquer MEASURE. Adotar se o goal virar financeiro.
- **S&T** como tipo próprio: ver (f).
- **Tipos de CLR como objetos**: basta o veredito por entidade/seta; objetos por reserva só se houver revisão
  adversarial frequente.
