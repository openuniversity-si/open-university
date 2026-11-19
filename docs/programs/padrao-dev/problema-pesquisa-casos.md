# Casos de uso, business case, decisão e specs de agentes: o que entra antes dos requisitos

Pergunta: o "use case" que Daniel citou vem da TOC ou é o business case adiado? O que mais a prática de elite e a
prática de agentes põem antes dos requisitos, e o que disso cabe no desenho v2
(`docs/programs/padrao-dev/problema-desenho.md`: INT, NC, MEAS, UDE, CAUSE, CONFLICT, P, INJ, EXP, D, OBST, NEED, WORK).

## 0. Resposta curta

- **Use case não vem da TOC.** É engenharia de software (Jacobson, 1987). Nenhum dos processos de pensamento
  (Goal Tree, CRT, nuvem, FRT, PRT, TT, S&T) tem "use case". O mais próximo na TOC são as **seis perguntas da
  tecnologia** de *Necessary but Not Sufficient* (Goldratt, Schragenheim, Ptak, 2000), que olham a solução pelo uso.
- **Use case também não é o business case.** São coisas diferentes e as duas faltam no v2:
  - o **use case / cenário operacional** fica no espaço da solução, entre a INJ escolhida e as NEED. É o conteúdo do
    OpsCon (15288 6.4.2; 29148 Anexo A, "operational scenarios"), que o v2 reduz a um documento "Conceito" sem
    estrutura;
  - o **business case** é a justificativa da escolha entre opções, mantida no ciclo de vida (ISO 21502 4.3.2;
    PRINCE2; Five Case Model). O v2 o adia por ser "monetário". Esse motivo não se sustenta: o business case não
    precisa ser monetário (custo-efetividade, MCDA), e a Torre tem custo real (cota de tokens, AWS) e um critério
    de escolha que o v2 não registra (pesos, notas, faixa de custo aceitável).
- **Recomendação:**
  - um objeto **SCEN** (cenário operacional / use case com fatias);
  - um objeto **CASE** (business case nas cinco dimensões, a maior parte derivada do grafo), com a **avaliação de
    opções** (`appraisal`) dentro da D ou ligada a ela;
  - quatro campos tirados de Shape Up / design docs: `appetite`, `no_gos`, `non_goals` e `rabbit_holes`, ligados
    aos ramos negativos.
  - User story, JTBD/ODI, PRD e PR-FAQ **não** viram objetos. Entram como gramática ou formato de campos que já
    existem.

## 1. Use cases, cenários, histórias, JTBD

### 1.1 Origem e elementos
- **Jacobson, OOSE.** O artigo de 1987 (OOPSLA, "Object-oriented development in an industrial environment") e o livro
  *Object-Oriented Software Engineering: A Use Case Driven Approach* (1992) criam o termo e o "use-case driven".
  O UML (OMG, 1997 em diante) padroniza o diagrama: ator, caso de uso, `include`, `extend`.
- **Cockburn, *Writing Effective Use Cases* (2001).** É o padrão de fato do texto.
  - Campos: escopo, **nível do objetivo** (summary/cloud, user-goal/sea level, subfunction), ator primário,
    **stakeholders e interesses**, **pré-condições**, **garantias mínimas** (o que vale mesmo em falha),
    **garantias de sucesso** (pós-condições), gatilho, **cenário principal de sucesso** e **extensões** (fluxos
    alternativos e de falha, numerados a partir do passo que desviam).
  - Regra: o use case é um **contrato de comportamento** entre stakeholders, e o ator primário persegue um objetivo.
- **Use-Case 2.0** (Jacobson, Spence, Bittner, dez. 2011; ACM Queue 2016, "Use-Case 2.0: The Hub of Software
  Development", Jacobson, Spence, Kerr).
  - O use case é fatiado em **use-case slices**: uma ou mais histórias (caminhos pelo fluxo) com **casos de teste**,
    cada fatia cabendo numa iteração.
  - A fatia atravessa requisito, desenho, código e teste. O fluxo básico vem primeiro, e o use case não precisa
    estar todo fatiado antes de começar.
  - Fontes: https://queue.acm.org/detail.cfm?id=2912151, https://t2informatik.de/en/smartpedia/use-case-2-0/
- **Cenário operacional (systems engineering).** A 15288:2023 6.4.2 desenvolve o OpsCon e outros conceitos de ciclo
  de vida. A 29148:2018 tem o Anexo A (normativo, OpsCon), com "operational scenarios" (A.2.7; era A.2.6 na edição
  2011), e o Anexo B (informativo, ConOps).
  - Um cenário é uma sequência imaginada de eventos que mostra como o sistema interage com o ambiente, os usuários e
    as próprias partes.
  - O NASA SE Handbook (Apêndice S) pede cenários **nominais e fora do nominal**, cada um com rótulo para
    rastreabilidade.
  - Fontes: https://www.nasa.gov/reference/appendix-s-concept-of-operations-annotated-outline e o sumário da 29148
    no iteh.
- **Onde fica:** depois da escolha da solução (classe ou conceito) e antes, ou junto, das necessidades. O cenário é
  a **fonte** das NEED e dos REQ de stakeholder, e a **base da validação**, porque a VAL roda os cenários. Não fica no
  espaço do problema.

### 1.2 User stories e story mapping
- **Formato e regras:**
  - Connextra (Rachel Davies, 2001): "As a <role> I want <capability> so that <benefit>";
  - 3C (Ron Jeffries, 2001): Card, Conversation, Confirmation;
  - INVEST (Bill Wake, 2003).
- **Patton, *User Story Mapping* (2014):**
  - a **espinha** (backbone) são as atividades do usuário em ordem narrativa, e abaixo dela ficam as histórias;
  - cortes horizontais formam as **fatias de entrega**, e a primeira é o *walking skeleton*;
  - na prática, é o equivalente ágil do use case com fatias.
- **Spec Kit** pede "User Scenarios & Testing" com histórias priorizadas (P1, P2…), cada uma **testável sozinha**,
  com cenários de aceitação Given/When/Then e "Success Criteria" mensuráveis (SC-001…).
  Fonte: https://github.com/github/spec-kit/blob/main/templates/spec-template.md
- **Julgamento:** a história é um *formato de enunciado* de necessidade ou de fatia, não um nível novo. No modelo da
  Torre, NEED já é "o que o stakeholder precisa, na língua dele", e WORK já é a fatia. Uma história não acrescenta
  informação que NEED + SCEN + WORK não tenham.

### 1.3 JTBD e ODI (o par do problema)
- **Christensen**, *Competing Against Luck* (2016): o cliente "contrata" um produto para fazer um *job*, com
  dimensões funcionais, sociais e emocionais.
- **Ulwick**, *What Customers Want* (2005), Outcome-Driven Innovation:
  - **job map** (os passos do job);
  - **desired outcome statements** com gramática fixa: direção + métrica + objeto + contexto (ex.: "minimizar o
    tempo para…"); devem ser livres de solução, estáveis e mensuráveis;
  - **opportunity score** = importância + max(importância − satisfação, 0).
  - Fontes: https://strategyn.com/customer-needs-through-a-jobs-to-be-done-lens/ (fonte do próprio fornecedor; a
    taxa de sucesso de 86% é marketing, não evidência).
- **Julgamento:** JTBD/ODI cobre o mesmo lugar da Goal Tree. Um outcome é uma **condição necessária medida**, e um
  outcome mal servido é um **UDE**. O ODI mede pela opinião de muitos clientes, mas a Torre tem um dono e medidas
  objetivas (MEAS), então pesquisa de importância e satisfação não se aplica.
  - **Aproveita-se a gramática:** o `statement` de uma NC segue "direção + métrica + objeto + contexto" e não pode
    conter solução. É uma regra de lint, não um objeto.
  - **Aproveita-se a ideia do score:** priorizar as NC por importância × gap. Importância vem de Daniel (pesos dos
    CSF), e o gap vem da ferramenta.

### 1.4 A TOC tem "use case"? Não. O que tem perto
- Os processos de pensamento são cinco diagramas e as regras lógicas (CLR). Goldratt os criou em 1990 e os ampliou em
  1994, e depois vieram a S&T e a Goal Tree de Dettmer (2007). Nenhum descreve a interação de um ator com um sistema.
  Fonte: https://www.wikipedia.org/wiki/Transition_Tree (Thinking processes); Davies & Mabin, *TOC Handbook*,
  cap. 23.
- **Necessary but Not Sufficient (2000)**, as seis perguntas de uma tecnologia:
  1. qual é o poder da tecnologia;
  2. que limitação ela diminui;
  3. que regras existiam para acomodar essa limitação;
  4. que regras usar agora;
  5. que mudanças a tecnologia precisa à luz das novas regras;
  6. como causar a mudança.
  - São a ponte TOC entre a solução e o uso. A pergunta 3/4 (as regras antigas que sobrevivem) é exatamente o que
    deixa um sistema de agentes caro: rotinas humanas mantidas depois que a limitação sumiu.
  - **Proposta:** campos de INJ quando `kind: mechanism` (tecnologia): `limitation_removed`, `old_rules[]`,
    `new_rules[]`. Cada old_rule vira P (premissa a refutar) ou OBST.
- **Conclusão:** se Daniel ouviu "use case" num contexto TOC, o mais provável é o uso coloquial ("caso de aplicação")
  ou as seis perguntas acima. Não é um artefato TOC.

## 2. Business case

### 2.1 Fontes
- **ISO 21502:2020 4.3.2:**
  - o business case justifica o início e a continuidade, com objetivos, opções, benefícios, custos, riscos e prazos;
  - ele é **mantido** e reavaliado nos pontos de decisão;
  - a realização de benefícios fica na 7.3, e a avaliação pós-projeto na ISO 21513.
- **PRINCE2** (tema/prática "Business Case"; princípio "continued business justification"):
  - sempre três opções: **do nothing** (a linha de base para quantificar as outras), **do minimum** e
    **do something**;
  - benefícios mensuráveis, cada um com baseline e forma de medir;
  - **dis-benefits**: efeitos negativos *certos* e aceitos, diferentes de riscos;
  - custos, prazos, investimento e riscos maiores;
  - verificado em cada fronteira de estágio.
  - Fontes: https://prince2.wiki/management-products/business-case; o texto oficial do PRINCE2 7 não foi lido.
- **MSP (5ª ed., 2020):** o business case do programa agrega os dos projetos e é ligado ao benefits map e aos
  benefit profiles.
- **HM Treasury Green Book + Five Case Model** (obrigatório no governo central do Reino Unido; revisto em 2025, nova
  edição em 2026):
  1. **Strategic case**: a razão para mudar, os *spending objectives* SMART, o escopo e os **critical success factors**
     (CSF);
  2. **Economic case**: a lista longa, filtrada pelo *options framework filter* (escopo, solução, entrega,
     implementação, financiamento), e a lista curta com **BAU/do-nothing**, **do-minimum** e a *preferred way
     forward*;
     - mede o valor social (NPSV, BCR) e os efeitos **não monetizados**;
     - usa análise de risco e otimismo (*optimism bias*);
  3. **Commercial case**: a viabilidade da contratação;
  4. **Financial case**: a acessibilidade (*affordability*) e o orçamento;
  5. **Management case**: a entrega, os benefícios, o risco e a avaliação.
  - **Etapas:** SOC → OBC → FBC (strategic outline, outline e full business case).
  - Fontes: https://www.gov.uk/government/collections/the-green-book-and-accompanying-guidance,
    https://www.england.nhs.uk/mids-east/wp-content/uploads/sites/7/2014/10/bus-cas-five-cas-mod-guide.pdf
- **Business case não monetário** (prática estabelecida):
  - **análise de custo-efetividade**: custo por unidade de resultado, quando o benefício não se monetiza;
  - **MCDA**: o *Multi-criteria analysis: a manual* (DCLG, 2009) e Keeney, *Value-Focused Thinking* (1992);
    critérios derivados dos objetivos, pesos, notas e análise de sensibilidade.
  - O Green Book aceita a MCDA sobretudo na triagem da lista longa (memória; texto exato não relido).

### 2.2 Relação com a TOC
- **Throughput Accounting** (Goldratt, *The Haystack Syndrome*, 1990; Corbett, 1998):
  - a decisão é julgada por **ΔT, ΔI, ΔOE**, e não por custo de produto;
  - Goldratt pede que uma organização sem fim de lucro meça T em **unidades da meta**.
  - Na Torre: T = PRs mergeados (ou o que a INT define) por unidade de tempo; I = trabalho em andamento e fila;
    OE = tokens, cota e AWS.
  - Isso é um business case TOC **não financeiro**, e muda o adiamento do v2 ("TA é financeiro"). T/I/OE em
    unidades da meta são justamente as três medidas de decisão do Economic case.
- **Necessary but Not Sufficient:** a tecnologia só traz benefício se as regras mudam. No business case, isso é o
  risco de benefício não realizado. No grafo, é o ramo negativo "old rules sobrevivem".
- **Conclusão:** a TOC não substitui o business case. Ela dá **a métrica de decisão** (ΔT/ΔI/ΔOE na restrição) e
  **a lógica** (FRT, ramos). O business case dá a **comparação formal entre opções**, a **acessibilidade** e a
  **manutenção ao longo do ciclo**.

## 3. Prática de decisão
- **ISO/IEC/IEEE 15288:2023 6.3.3, Decision Management:**
  - é um "structured analytical framework for identifying, characterizing and evaluating alternatives";
  - as atividades são preparar (estratégia e critérios), analisar (alternativas contra critérios) e decidir/registrar
    (a escolha, o porquê, as premissas);
  - a sequência INCOSE/SEBoK é: frame decision → develop objectives and value measures → generate alternatives →
    assess → synthesize → uncertainty/sensitivity → improve alternatives.
  - Fontes: https://sebokwiki.org/wiki/Decision_Management (não acessível daqui; citado pelo resumo da busca);
    Parnell et al., *Trade-off Analytics* (2017), cap. 5.
- **ADR** (Nygard, 2011; MADR: contexto, decision drivers, opções consideradas, prós e contras, decisão,
  consequências):
  - é decisão de **arquitetura**, no espaço da solução técnica, depois dos REQ;
  - a decisão de **negócio** (qual problema, qual INJ, quanto gastar) pertence ao portfólio/programa.
  - **Na Torre:** os dois são D-NNN. Basta um campo `level: business | architecture` e, para `business`, a avaliação
    de opções obrigatória.
- **Elite:** critérios **declarados antes de pontuar** (evita racionalização a posteriori), um "não fazer" pontuado,
  sensibilidade dos pesos e caminho de volta. Isso já é a regra da casa (D-294 e "a opção reversível").

## 4. Specs e agentes hoje (credível ou marketing)
| Prática | Artefatos | Antes dos requisitos? | Legível por máquina | Juízo |
|---|---|---|---|---|
| GitHub Spec Kit (2025) | `constitution.md`, `spec.md` (histórias P1..., Given/When/Then, FR-NNN, SC-NNN, `[NEEDS CLARIFICATION]`), `plan.md`, `tasks.md` | Só a spec (nível NEED/REQ); sem problema, opções ou benefício | Markdown com IDs; o agente lê e escreve | Credível como prática aberta; os IDs FR/SC e o marcador de dúvida são boas ideias. Não tem laço de benefício |
| Amazon Kiro | `.kiro/specs/<f>/requirements.md` (histórias + critérios **EARS**: WHEN… THE SYSTEM SHALL…), `design.md`, `tasks.md` (executáveis, com estado); `bugfix.md`; "steering" | Não; começa no requisito | Markdown semiestruturado; EARS é gramática (Mavin et al., RE'09, credível) | EARS é sólido; o resto é produto. https://kiro.dev/docs/specs/concepts |
| Anthropic (Claude Code best practices) | explore → plan → code → commit; Plan Mode; verificação como alvo | Separa pesquisa e plano da execução "para não resolver o problema errado" | Não define artefato | Orientação de processo, credível, sem modelo de dados. https://code.claude.com/docs/en/best-practices |
| OpenAI (Codex / AGENTS.md) | `AGENTS.md` como instrução persistente | Não | Markdown livre | Convenção, não método |
| PRD (Cagan, 2005; SVPG depois critica o PRD como substituto da descoberta) | problema, objetivos e métricas, personas, requisitos, fora de escopo | Mistura problema e requisito | Documento | Prática difundida e mal definida; sem padrão |
| Shape Up pitch (Basecamp, 2019) | **problem, appetite, solution** (fat-marker), **rabbit holes**, **no-gos** | Sim: problema + orçamento + forma da solução antes de apostar | Documento | Credível (livro aberto). https://basecamp.com/shapeup/1.5-chapter-06 |
| Amazon PR-FAQ (Bryar & Carr, *Working Backwards*, 2021) | comunicado do futuro + FAQ externa e interna | Sim: o cliente, o problema e o benefício primeiro | Documento narrativo | Credível como disciplina de escrita |
| Google design doc (Ubl, 2020, industrialempathy.com) | context and scope, **goals and non-goals**, design, **alternatives considered**, cross-cutting concerns | Parcial: no nível da arquitetura | Documento | Credível, mas é nível de desenho técnico |

- **Achado central:** nenhuma prática de agentes credível tem o espaço do problema como **objetos tipados**. Todas
  começam na spec (história e requisito) e usam Markdown. O que agentes aproveitam de verdade:
  - IDs estáveis;
  - gramática restrita (EARS, Given/When/Then);
  - marcadores explícitos de dúvida;
  - tarefas com estado;
  - critérios de sucesso medidos.
- **Vantagem do modelo da Torre:** objetos JSON com links checados levam essa disciplina para antes dos requisitos.
  Isso está à frente da prática publicada; não há referência a copiar.
- **Marketing a descontar:** taxas de sucesso de fornecedores (Strategyn), "spec-driven elimina retrabalho" (blogs de
  ferramentas) e skills de terceiros que redefinem rabbit holes como no-gos.

## 5. Cada candidato contra o modelo v2: cabe? como? quem/quando

| Candidato | Origem | Cabe? | Forma no modelo | Quem / quando |
|---|---|---|---|---|
| **Use case / cenário operacional** | Jacobson 1987/92; Cockburn 2001; UC 2.0; 29148 An. A; 15288 6.4.2 | **Sim, objeto novo SCEN**: o v2 tem só "Conceito" sem estrutura, e sem cenários as NEED não têm fonte verificável nem a VAL um roteiro | ver §6.1 | sessão escreve / desenho (depois da D que escolhe a INJ, antes das NEED); Daniel valida os de nível `summary`; ferramenta checa cobertura |
| **Use-case slice / story map** | UC 2.0; Patton 2014 | Sim, como **ligação**, não como objeto: WORK `slices` → SCEN (passos/extensões cobertos) | o story map é **vista derivada** (SCEN × WORK) | ferramenta / entrega |
| **User story** | Connextra 2001; Jeffries; Wake | Não como objeto: é formato de NEED (`role`, `capability`, `benefit` ↔ `serves` NC) | gramática opcional do `statement` da NEED | sessão / desenho |
| **JTBD / ODI** | Christensen 2016; Ulwick 2005 | Não como objeto: já é a Goal Tree (outcome = NC; mal servido = UDE) | regra de lint na NC (direção+métrica+objeto+contexto, sem solução); campo `weight` (importância) por CSF | Daniel dá os pesos / antes; ferramenta aplica o lint |
| **Business case (CASE)** | ISO 21502 4.3.2; PRINCE2; MSP; Green Book | **Sim, objeto novo CASE por programa, em sua maior parte derivado** | ver §6.2 | ver §6.2 |
| **Avaliação de opções** | Green Book (lista longa/curta, do-nothing, do-minimum); PRINCE2; 15288 6.3.3; MCDA | **Sim, obrigatória na D de nível business**: o v2 tem INJ "não fazer" mas não tem critérios, pesos, notas nem sensibilidade | `appraisal` dentro da D (§6.3) | sessão propõe critérios **antes** de pontuar; Daniel aceita os pesos; ferramenta calcula e faz a sensibilidade / desenho |
| **PRD** | Cagan 2005 | Não: é um documento-pacote cujas partes já são objetos (NC, NEED, REQ, `no_gos`) | vista gerada, se alguém pedir | ferramenta / qualquer momento |
| **Shape Up pitch** | Basecamp 2019 | Parcial: entram `appetite` e `no_gos`; problem = UDE/CAUSE; solution = INJ + SCEN; rabbit holes = ramos negativos e OBST | campos em INJ/CASE (§6.4) | Daniel fixa o apetite do programa; sessão o propõe por INJ / antes e desenho |
| **PR-FAQ** | Amazon (Bryar & Carr 2021) | Não como objeto: o "comunicado" é a FRT narrada (os efeitos desejados com o UDE invertido); a FAQ interna é P + ramos | `solucao.md` pode abrir com o comunicado, gerado dos efeitos da INJ | sessão / desenho, opcional |
| **Seis perguntas (NBNS)** | Goldratt et al. 2000 | Sim, campos de INJ `kind: mechanism` | `limitation_removed`, `old_rules[]` (→ P/OBST), `new_rules[]` | sessão / desenho |
| **Design doc (goals/non-goals, alternatives)** | Google | Já coberto depois do REQ (arquitetura); os non-goals entram junto com `no_gos` | D `level: architecture` com opções | sessão / entrega |

## 6. Objetos e campos propostos

### 6.1 SCEN: cenário operacional / use case
- **Campos:**
  - `title`;
  - `level`: summary | user-goal | subfunction (Cockburn);
  - `primary_actor`: Daniel | session | tool | torre | merge-queue | external;
  - `stakeholders[]` {who, interest};
  - `trigger` (o evento do contrato de eventos, quando houver);
  - `preconditions[]`;
  - `main_flow[]` {n, actor, action};
  - `extensions[]` {at_step, condition, flow[], kind: alternate | failure};
  - `minimal_guarantees[]` e `success_guarantees[]`;
  - `nominal`: bool;
  - `state`: draft | validated | retired.
- **Ligações:**
  - `realizes` → INJ escolhida (obrigatória);
  - `yields` → NEED (cada NEED deriva de pelo menos um SCEN ou da INJ);
  - `includes` / `extends` → SCEN;
  - `validated-by` → VAL (a VAL executa o cenário);
  - WORK `slices` → SCEN {steps[]}.
- **Regras:**
  - toda INJ escolhida tem um SCEN `user-goal` nominal e um fora do nominal;
  - toda extensão `failure` tem garantia mínima;
  - toda NEED tem fonte (SCEN ou INJ);
  - todo SCEN `validated` tem VAL.
- **Por que no nível de elite:** 29148 An. A, NASA ConOps (nominal e off-nominal) e UC 2.0 (fatia = teste). Para
  agentes, os passos numerados com ator são a especificação de comportamento mais executável que existe antes do REQ.
  A Torre já tem atores reais e um contrato de eventos, então os gatilhos são concretos.

### 6.2 CASE: business case do programa (Five Case Model, adaptado)
| Dimensão | Conteúdo | No grafo (derivado) | Escrito à mão |
|---|---|---|---|
| strategic | por que mudar; objetivos; CSF; escopo | INT, NC (CSF com alvo), UDE, CAUSE central, CONFLICT | `scope`, `no_gos[]` |
| economic | opções e valor | INJ candidatas, incl. `do-nothing` e `do-minimum` obrigatórias; ΔT/ΔI/ΔOE em unidades da meta por INJ (EXP ou estimativa com P); dis-benefits = ramos negativos `accepted_by` D | `appraisal` (§6.3) |
| commercial | fornecedores e contratos | — | `dependencies[]` {vendor: Anthropic cota, AWS, GitHub; limite; risco}; quase sempre curto, mas nunca vazio por omissão |
| financial | acessibilidade | leitura de MEAS de custo (tokens/dia, cota da janela, US$ AWS/mês) | `budget` {tokens, usd, by}; qualquer dinheiro novo é decisão de Daniel (regra da casa) |
| management | como entregar e medir | OBST, WORK, EXP, plano de benefício = NC com alvo e data | `review_points[]` (antes, desenho, entrega, depois), `revert_path` |

- **Campos de ciclo de vida:** `stage`: outline (antes) | full (desenho) | maintained (entrega) | closed (depois).
  Mesma lógica de SOC/OBC/FBC.
- **Campos de veredito:** `verdict_by_point[]` {point, still_justified: bool, why, D}.
- **Ligações:**
  - `justifies` → D (business);
  - `for` → programa;
  - `superseded-by` → CASE.
- **Regras:**
  - um programa tem CASE antes da D que escolhe a INJ;
  - todo ponto de revisão tem veredito;
  - "justificado" falso abre D de parar ou ajustar (continued justification);
  - na etapa closed, o CASE cita os benefícios (estado das NC) contra o previsto.
- **Quem:** a sessão monta o rascunho, e a ferramenta deriva as quatro colunas do grafo. Daniel aceita o
  `budget`/`appetite` e o veredito de continuar ou parar quando há dinheiro ou mudança de intenção. Nos outros casos,
  a sessão decide pela D-294 com caminho de volta.
- **Por que não adiar:** o motivo do v2 ("a Torre não decide por retorno financeiro") ataca o business case
  *monetário*, mas ISO 21502, PRINCE2 e Green Book exigem a **justificativa contínua com opções e acessibilidade**,
  não o dinheiro. A Torre gasta cota e AWS (D-327: o caminho mais barato), e hoje esse critério vive em texto de
  commit, sem objeto que a retrospectiva leia.

### 6.3 `appraisal` (na D de nível business)
- **Campos:**
  - `criteria[]` {id, derived_from: NC, weight, scale}, fixados **antes** das notas (carimbo de data);
  - `options[]` → INJ, sempre incluindo do-nothing e do-minimum;
  - `scores[]` {option, criterion, value, evidence: EXP | MEAS | P};
  - `cost` {tokens, usd, wall} por opção;
  - `cost_effectiveness` (custo por unidade de ΔNC);
  - `sensitivity` {weights_perturbed, winner_stable: bool};
  - `optimism_adjustment` (Green Book), quando a estimativa não vem de EXP.
- **Regras:**
  - um critério sem NC é refutado (o critério vem dos objetivos, Keeney);
  - uma nota sem evidência vira P `to-validate`;
  - um vencedor instável à sensibilidade exige EXP ou decisão explícita.

### 6.4 Campos tirados de Shape Up, design docs e NBNS
- **INJ:**
  - `appetite` {tokens, wall, prs}: orçamento fixo, escopo variável; ultrapassar é um evento que reabre a D;
  - `no_gos[]`;
  - `rabbit_holes[]` → cada um é ramo negativo com `trimmed_by` ou OBST;
  - para `kind: mechanism`: `limitation_removed`, `old_rules[]`, `new_rules[]`.
- **NC:** `weight` (importância, por Daniel nos CSF); lint de gramática ODI.
- **NEED:** gramática opcional de história; `derives-from` → SCEN ou INJ.
- **D:** `level`: business | architecture; `appraisal` obrigatório em business.

## 7. Ordem atualizada (só o que muda no §4 do v2)
1. **Antes:**
   - Daniel dá a INT e os pesos dos CSF;
   - a sessão abre o CASE `outline` (strategic derivado; `no_gos`, `appetite` do programa, `budget`);
   - Daniel aceita o apetite e o orçamento quando envolvem dinheiro ou cota fora do normal.
2. **Desenho:**
   - depois das INJ e da FRT, a sessão escreve os critérios do `appraisal` **antes** das notas e inclui do-nothing e
     do-minimum;
   - a ferramenta pontua e faz a sensibilidade;
   - a D é registrada, e o CASE passa a `full`;
   - em seguida, a sessão escreve os SCEN (nominal e fora do nominal) da INJ escolhida, depois as NEED dos SCEN e
     os OBST.
3. **Entrega:**
   - cada WORK declara `slices` → SCEN;
   - a VAL executa os SCEN;
   - nos pontos de revisão, a ferramenta compara o consumo com o `appetite`/`budget` e o ΔNC com o previsto, e a
     sessão registra o veredito de justificativa contínua.
4. **Depois:**
   - o CASE `closed` compara benefício previsto e realizado e os dis-benefits;
   - a LESSON cita o CASE.

## 8. Limites
- Textos normativos pagos (15288, 29148, 21502, PRINCE2 7, MSP) não foram lidos. As cláusulas vêm de sumários
  públicos; o Anexo A/A.2.7 da 29148 foi confirmado só pelo sumário.
- O detalhe sobre MCDA no Green Book (uso na lista longa) vem de memória.
- Autoria do UC 2.0: o livro é Jacobson/Spence/Bittner (2011), e o artigo da ACM Queue é Jacobson/Spence/Kerr (2016).
- Kiro: só a documentação oficial é tomada como fato; o que skills de terceiros acrescentam ("correctness
  properties", grafo de dependência) não é.
