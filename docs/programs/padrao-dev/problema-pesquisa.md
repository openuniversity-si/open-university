# O que vem antes dos requisitos: estado da arte e modelo de referência

Pergunta (Daniel): a cadeia NEED -> REQ -> arquitetura -> construção -> verificação -> validação -> conformidade
é o começo real? O que a indústria faz antes dos requisitos, e onde termina o sistema maior?

## 0. Resposta curta

- **Não, NEED não é o começo.** Em toda fonte autoritativa, a cadeia começa num **problema ou oportunidade**
  (uma situação a mudar), medido contra objetivos do negócio/missão, com a análise do **estado atual vs. estado
  desejado** e das **classes de solução candidatas**. Só depois de escolhido um conceito de solução nascem as
  necessidades dos stakeholders (NEED) e, delas, os requisitos (REQ).
- **Sim, REQ -> ... -> conformidade é um subsistema.** Na ISO/IEC/IEEE 15288:2023 ele é parte dos *processos
  técnicos* (6.4), que por sua vez são um de quatro grupos (acordo 6.1, habilitação organizacional 6.2 — inclui
  gestão de portfólio 6.2.3 —, gestão técnica 6.3, técnicos 6.4).
- **O sistema maior fecha no benefício medido**, não na conformidade: validação diz "o sistema atende à
  necessidade"; a **realização de benefícios** (ISO 21502:2020 §7.3; ISO 21513; MSP) diz "o problema mudou como
  pretendido". A medida de resultado volta ao problema/oportunidade e ao portfólio (decidir continuar, ajustar,
  parar). Esse é o laço que fecha.

## 1. Fontes e o que cada uma diz

| # | Fonte | O que está antes dos requisitos |
|---|---|---|
| S1 | ISO/IEC/IEEE 15288:2023, 6.4.1 Business or Mission Analysis (BMA) | Definir o **espaço do problema/oportunidade**; caracterizar o **espaço de solução**; identificar e avaliar **classes de solução alternativas**; selecionar a classe preferida; **conceitos de ciclo de vida preliminares** (operacional, etc.). Roda iterativamente com 6.4.2. (texto normativo não lido; resumo de [SEBoK BMA](https://sebokwiki.org/wiki/Business_or_Mission_Analysis), [iteh 15288:2023 TOC](https://iteh.eu/catalog/standards/iso/4109ef6c-8070-4ebe-89d8-c45ae8413981/iso-iec-ieee-15288-2023), [ANSI blog](https://blog.ansi.org/ansi/iso-iec-ieee-15288-2023-system-life-cycle-processes/)) |
| S1b | 15288:2023, 6.4.2 Stakeholder Needs and Requirements Definition | Identificar stakeholders; definir **necessidades**; desenvolver **conceito operacional (OpsCon)** e outros conceitos de ciclo de vida; **transformar necessidades em requisitos de stakeholder**. Só depois 6.4.3 System Requirements Definition. |
| S1c | 15288:2023, 6.2.3 Portfolio Management; 6.3.3 Decision Mgmt; 6.3.7 Measurement; 6.1 Agreement | O "sistema maior": portfólio decide quais projetos existem e os encerra; decisão e medição governam. |
| S2 | ISO/IEC/IEEE 29148:2018 (cl. 6.2 BMA, 6.3 stakeholder needs; cl. 9 itens de informação) | Documentos **BRS** (Business Requirements Spec: problema, missão, objetivos do negócio, modelo de negócio, conceito de operações de alto nível), **StRS** e **OpsCon/ConOps**; distinção explícita **necessidade vs requisito** (necessidades transformadas em declarações estruturadas e verificáveis). ([iteh 29148](https://standards.iteh.ai/catalog/standards/iso/8cf2bc2b-8b5e-4907-a82a-d1c5676c9e85/iso-iec-ieee-29148-2018), [ReqView templates](https://reqview-homepage.netlify.app/doc/iso-iec-ieee-29148-templates)) |
| S3 | INCOSE Needs and Requirements Manual (INCOSE-TP-2021-002-01, ed. 2024) | §4.3.1 **Problem, threat or opportunity**; §4.3.2 **Mission, Goals, Objectives (MGOs)** e **measures** (MOE/MOP/KPP/TPM); análise de **lifecycle concepts**; saída = **integrated set of needs** (§2.1.2.1), validado antes de virar requisitos; needs -> design inputs (requirements). ([INCOSE RWG](https://www.incose.org/group/requirements-working-group/), [webinar 152](https://www.incose.org/wp-content/uploads/legacy/professional-development-portal/pdp-pdf-documents/webinar_152_wolfgang_need_help_with_requirements.pdf), [Lignina](https://lignina.com/en/book/incose-needs-and-requirements-manual-262c8c258555)) |
| S4 | INCOSE SE Handbook v5 (2023) | Segue a estrutura da 15288:2023; BMA e conceitos (ConOps no nível organizacional, OpsCon no nível do sistema); medidas MOE -> MOP -> TPM. (conhecimento do padrão; não relido aqui) |
| S5 | IIBA BABOK v3, cap. 6 Strategy Analysis | 6.1 **Analyze Current State** (necessidade de negócio, baseline, métricas/KPIs); 6.2 **Define Future State** (goals/objectives, valor potencial); 6.3 **Assess Risks**; 6.4 **Define Change Strategy** (gap analysis, opções, transições). Cap. 8 **Solution Evaluation** (medir desempenho e valor depois). Business case é técnica (10.7). ([IIBA task cards](https://www.iiba.org/contentassets/89ba1e5892a440f4b91974f43abb4d5f/all-task-cards-strategy-analysis.pdf), [Watermark](https://www.watermarklearning.com/blog/babok-strategy-analysis/)) |
| S6 | Teresa Torres, *Continuous Discovery Habits* (2021): Opportunity Solution Tree | **Desired outcome** -> **opportunities** (necessidades/dores do cliente) -> **solutions** -> **assumption tests**. ([Product Talk](https://producttalk.org/opportunity-solution-tree)) |
| S7 | Amazon Working Backwards / PR-FAQ | Cinco perguntas: quem é o cliente, **qual o problema/oportunidade**, benefício mais importante, como sabemos, como é a experiência; PR-FAQ antes de qualquer especificação. ([AWS re:Invent 2020 INO206](https://d1.awsstatic.com/events/reinvent/2020/Working_Backwards_Amazons_approach_to_innovation_INO206.pdf)) |
| S8 | Design Council Double Diamond | Discover/Define (espaço do problema) -> Develop/Deliver (espaço da solução). (conhecimento geral; busca sem resultado primário) |
| S9 | Lean Startup / hypothesis-driven development; Cynefin (Snowden) | Em domínio complexo, **probe-sense-respond**: experimentos/protótipos antes de fixar requisitos. (conhecimento geral) |
| S10 | ISO 21502:2020 §4.3.2 Business case, §7.3 Benefit management (7.3.2 identificar, 7.3.3 monitorar, 7.3.4 manter); ISO 21513 avaliação pós-projeto; MSP (benefits map/profiles); NSW BRM Framework | **Business case** justifica antes; **benefícios** medidos depois da entrega, inclusive após o projeto. Outcome != benefit: benefício é a mudança positiva mensurável resultante do outcome. ([ANSI 21502](https://blog.ansi.org/ansi/iso-21502-2020-project-management-guidance/), [ISO 21513](https://standards.iteh.ai/catalog/standards/iso/9b780779-8c41-49df-8468-7bee5ee04a75/iso-21513), [NSW BRM](https://www.nsw.gov.au:443/sites/default/files/2020-11/brmf%20guidelines.pdf)) |
| S11 | Google OKRs (Doerr, *Measure What Matters*) | Objective (qualitativo) + Key Results (medidos) acima de iniciativas. (conhecimento geral) |
| S12 | GitHub Spec Kit (spec-driven development, 2025) | constitution -> specify -> plan -> tasks -> implement; a spec carrega "por quê/para quem" (user stories, critérios), mas **não** tem objeto de problema/outcome/benefício nem laço de volta. ([Microsoft devblog](https://devblogs.microsoft.com/blog/spec-driven-development-spec-kit), [MS Learn](https://learn.microsoft.com/en-us/training/modules/spec-driven-development-github-spec-kit-enterprise-developers/3-examine-github-spec-kit)) |

## 2. Modelo de referência sintetizado (ordem, propósito, campos, links)

Dois espaços: **problema** (PROB, MGO, STATE, CAUSE) e **solução** (OPT, EXP, CONCEPT), com NEED como a ponte.

| Ordem | Objeto (id sugerido) | Propósito | Campos típicos | Links (tipados) |
|---|---|---|---|---|
| 1 | **PROB** problem/opportunity/threat | A situação a mudar, sem solução embutida | statement (quem sofre, o quê, onde, quando, impacto); kind problem/opportunity/threat; evidência; owner; data | `motivates` -> MGO; `affects` -> stakeholders |
| 2 | **MGO** mission/goal/objective (ou OKR/outcome) | O que significa "resolvido" | mission; goals; objetivos com **medida** (MOE/KR: métrica, baseline, alvo, prazo) | `addresses` -> PROB; `measured_by` -> MEASURE |
| 3 | **STATE** current/future state + **gap** | Baseline medido e estado alvo; o gap é a distância nas mesmas medidas | métricas atuais (valor, fonte, data); estado futuro; gap por métrica | `baseline_of` / `target_of` -> MGO |
| 4 | **CAUSE** root cause / opportunity driver (opcional) | Por que o gap existe; evita tratar sintoma | causa; evidência; método (5 porquês, Ishikawa, opportunity tree) | `explains` -> PROB/gap |
| 5 | **OPT** candidate solution class / option | Alternativas no espaço de solução (incl. "não fazer") | descrição; custo; risco; valor estimado; critérios de decisão | `addresses` -> CAUSE/PROB; `evaluated_by` -> EXP; `decided_in` -> DECISION |
| 6 | **EXP** experiment / prototype / PoC / assumption test | Reduzir incerteza antes de comprometer requisitos (Cynefin complexo) | hipótese; premissa testada; método; critério de sucesso; resultado | `tests` -> OPT; `confirms`/`refutes` -> premissa |
| 7 | **DECISION** + **business case** | Escolha da opção e justificativa (custo x benefício x risco) | opção escolhida; rejeitadas e por quê; benefícios esperados; reversão | `selects` -> OPT; `justified_by` -> MGO |
| 8 | **CONCEPT** ConOps/OpsCon / lifecycle concepts | Como a solução escolhida será usada/operada/mantida; fonte das necessidades | cenários; atores; modos; ambiente; restrições | `realizes` -> OPT escolhida; `yields` -> NEED |
| 9 | **NEED** stakeholder need (integrated set of needs) | O que os stakeholders precisam da solução, no idioma deles | statement; stakeholder; rationale; método de validação | `derived_from` -> CONCEPT/MGO; `validated_by` -> VAL |
| 10 | **REQ** (stakeholder/system requirement) | Declaração verificável, "shall" | (o que já existe) | `derived_from` -> NEED; `verified_by` -> VER |
| ... | arquitetura, construção, VER, VAL, conformidade | (subsistema existente) | | |
| último | **BENEFIT** realization record | O problema mudou? Medida de outcome depois da operação | medida; baseline; valor observado; data; atribuição; desbenefícios | `measures` -> MGO; `closes`/`reopens` -> PROB |

Rastreabilidade para baixo: PROB -> MGO -> (STATE/CAUSE) -> OPT -> DECISION -> CONCEPT -> NEED -> REQ -> ...
Para cima (o laço): VER prova REQ; **VAL** prova NEED (e o CONCEPT); **BENEFIT** prova MGO (e, portanto, PROB).
Regra correspondente (V-model estendido): cada nível à esquerda tem seu par de prova à direita;
o par de PROB/MGO é a medida de benefício, não a validação.

## 3. Consenso vs. fonte única

Consenso (2+ fontes autoritativas):
- **Problema/oportunidade antes da solução**: S1 (6.4.1), S2, S3 (§4.3.1), S5 (business need), S6 (outcome/opportunity), S7, S8.
- **Objetivos com medidas definidos antes dos requisitos**: S1/S3 (MGOs, MOE/MOP), S5 (goals/objectives, KPIs), S6 (outcome), S10, S11.
- **Estado atual / estado futuro / gap**: S5 (6.1, 6.2, 6.4) e S1 (BMA define espaço do problema e de solução); também S10 (baseline de benefícios).
- **Alternativas de solução avaliadas antes de escolher**: S1 (solution classes), S5 (change strategy options), S6 (múltiplas soluções por oportunidade), S10 (business case com opções).
- **Conceitos (ConOps/OpsCon) entre a solução escolhida e as necessidades**: S1b, S2, S3, S4.
- **Necessidade != requisito** (necessidades transformadas em requisitos): S1b, S2, S3, S4.
- **Benefícios medidos após entrega fecham o laço**: S5 (Solution Evaluation), S10 (ISO 21502 §7.3, 21513, MSP), S6 (outcome como raiz e medida).
- **Experimentos antes de comprometer**: S6, S9, S7 (iteração do PR-FAQ); em SE clássica aparece como análise/protótipos em BMA, menos explícito.

Fonte única ou fraca:
- **Root cause como objeto próprio**: forte em qualidade/lean (A3, 8D) e BABOK (técnica), mas não como artefato obrigatório em 15288/NRM. Tratar como opcional.
- **Integrated set of needs** como artefato formal validado: INCOSE (S3/S4) apenas.
- **PR-FAQ** (S7), **Opportunity Solution Tree** (S6), **Cynefin** (S9): cada um de uma escola; úteis como prática, não norma.
- **Spec-driven development com problema como artefato de máquina** (S12): não há fonte credível de objeto PROB/MGO/BENEFIT tipado para agentes; Spec Kit começa na spec (nível NEED/REQ) e não fecha o laço de benefício. Ponto em aberto da indústria, não consenso.

## 4. Onde termina o sistema maior

Camadas (de dentro para fora):
1. **Engenharia da solução** (15288 6.4.3–6.4.11): REQ -> ... -> VER -> VAL -> conformidade. Termina em "o sistema certo, construído certo".
2. **Definição do problema e da solução** (15288 6.4.1–6.4.2; BABOK cap. 6; NRM §4.3): PROB -> MGO -> OPT -> CONCEPT -> NEED.
3. **Operação e evolução** (15288 6.4.12–6.4.14 operação, manutenção, descarte): o sistema em uso gera dados.
4. **Gestão de benefícios / valor** (ISO 21502 §7.3; ISO 21513; MSP; BABOK cap. 8): o outcome medido contra o baseline do MGO.
5. **Portfólio e estratégia** (15288 6.2.3 Portfolio Management; ISO 21504 portfólio; OKRs): decide quais problemas atacar, reprioriza, encerra.

O laço fecha quando **a medida de benefício volta ao PROB/MGO** com um veredito (resolvido, parcial, piorou)
e **o portfólio decide** (encerrar, novo ciclo, nova opção). Não há fim absoluto: o limite prático é a
**intenção/estratégia da organização** (no caso da Torre: a intenção da SEMENTE, cujo único validador é Daniel).
Ou seja, a hierarquia é: intenção/estratégia -> portfólio de problemas/oportunidades -> MGO medido ->
solução -> NEED -> REQ -> ... -> VAL -> operação -> BENEFIT -> volta ao portfólio.

Observação para o modelo atual: os NEED-* de hoje parecem misturar dois níveis — intenção/objetivo
(espaço do problema, MGO) e necessidade de stakeholder sobre uma solução (espaço da solução). Separar isso é a
correção de maior valor.

## 5. Subconjunto mínimo mais barato (repositório de objetos JSON com links tipados)

Caminho mais barato: **2 tipos novos + 1 registro de medida + 4 links**, reutilizando o que já existe
(decisões D-NNN como DECISION, premissas P-NN como hipóteses de EXP, REQ/NEED já existentes).

Tipos mínimos:
1. **PROB-*** (problema/oportunidade) — `statement`, `kind` (problem|opportunity|threat), `evidence` (refs),
   `owner`, `status` (open|addressed|closed|reopened).
2. **OBJ-*** (objetivo medido; funde MGO + STATE) — `addresses: PROB-*`, `measure` {`metric`, `source`
   (comando/registro que mede, p.ex. `flow-metrics`), `baseline` {value, date}, `target` {value, by}}.
   O gap é derivado (target - baseline), não armazenado.
3. **BENEFIT-*** (observação; pode ser um array de leituras dentro do OBJ em vez de arquivo) — `measures: OBJ-*`,
   `value`, `date`, `source_ref`, `verdict` (met|partial|not_met).

Links mínimos (tipados, verificáveis por script):
- `NEED.derived_from -> OBJ` (obrigatório: nenhum NEED órfão de objetivo)
- `OBJ.addresses -> PROB`
- `OBJ.decided_in -> D-NNN` (a decisão que escolheu a solução; dispensa objetos OPT/DECISION separados — as
  alternativas rejeitadas ficam no texto da decisão)
- `BENEFIT.measures -> OBJ` (fecha o laço; um OBJ sem leitura após entrega é "benefício não medido")

Checagens que isso habilita (baratas, só grafo): NEED sem OBJ; OBJ sem PROB; OBJ sem medida/baseline; OBJ
com REQs todos verificados/validados mas sem BENEFIT; PROB `closed` sem BENEFIT `met`.

Fora de escopo no mínimo (adiar até uma medida pedir):
- CAUSE como objeto (usar campo texto em PROB ou incidente existente).
- OPT/EXP como objetos (usar a decisão D-NNN e premissas P-NN; promover a objeto só se alternativas forem
  reavaliadas com frequência).
- CONCEPT/ConOps formal (um campo `concept` em texto no OBJ ou link a um doc basta).
- Hierarquia MOE/MOP/KPP/TPM separada (uma medida por OBJ; MOP/TPM já vivem como REQ verificáveis).
- Business case com custo/benefício monetário, gestão de portfólio formal, benefits map do MSP.
- Ferramentas de spec-driven (Spec Kit etc.) — não acrescentam o espaço do problema.

## 6. Limites desta pesquisa

- Textos normativos (15288, 29148, NRM, BABOK, 21502) não foram lidos diretamente (pagos); números de cláusula
  vêm de sumários/TOCs públicos e conhecimento prévio. A cláusula 7.3 de 21502 e 6.4.1/6.4.2 de 15288:2023 foram
  confirmadas em TOCs; as cláusulas de 29148 (6.2/6.3/9) e BABOK 10.7 vêm de memória.
- sebokwiki.org não resolve nesta sessão (fora da allowlist de rede); citado a partir do resumo da busca.
- Double Diamond, Cynefin, OKRs, Lean Startup: conhecimento geral, sem fonte primária buscada aqui.
