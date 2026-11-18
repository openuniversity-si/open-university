# PADRAO-DEV — as 16 regras sem decisão

Pedido de Daniel (18/11/2026, 19:03 BRT, pela Torre): a PR #230 deu a decisão que as estabelece a 29 das 45 regras
semeadas em `config/standard/rules/STD-*.json`. Sobraram 16 com o `basis` vazio, cada uma com uma `note` terminada em
"No basis: ...". Antes de formalizar qualquer decisão, Daniel quer uma avaliação cuidadosa, sem pressa. Este documento
segue o [método](../../padrao/METODO.md) como os outros do programa: avaliação, pesquisa, análise e solução. Foi medido
sobre `main` em `97cd769`. Nenhuma decisão foi registrada. Os rascunhos abaixo levam nomes `D-rascunho-X` e esperam Daniel.

## Resposta de Daniel (18/11 20:19 BRT)
Pela Torre, literal: "pode aprovar, pode seguir com isso aí" e "tudo o restante pode confirmar e vamos seguir em frente".
- **Aprovados e registrados:** A → [D-324](../../domain/decisions/D-324.md) (o contrato dos registros), B →
  [D-325](../../domain/decisions/D-325.md) (decidir, depois reportar; as ordens de 26/10 e 02/11 confirmadas como dele),
  D → [D-326](../../domain/decisions/D-326.md) (a regra dormente), F → [D-327](../../domain/decisions/D-327.md) (o
  esforço mais barato como pergunta na hora de decidir, não como regra que barra PR), E →
  [D-328](../../domain/decisions/D-328.md) (as seis aposentadorias) e a pergunta 1, opção (a) →
  [D-329](../../domain/decisions/D-329.md) (o `pr metadata` volta ao `tower/gate`, lendo a PR do GitHub).
- **Já aplicado:** as nove regras de A, B e D têm `basis` e a `note` "Basis: ...". O código do E, o estágio do
  `pr metadata`, o estado `dormant` do D e as reescritas de enunciado vêm em PRs próprias, que citam esses números.
- **C (o método de gestão) não foi aprovado em 20:19:** esperava a pergunta sobre o grupo de gestão.

## Resposta de Daniel (18/11 20:31 BRT)
Pela Torre, literal: "manda é pra esperar meu ok em nada não. Meu ok é pra ser esperado situações muito específicas,
normalmente quando envolve dinheiro ou outras pessoas." A Torre mandou seguir com a recomendação: a gestão vira um
grupo de sistemas separado (intenção, trabalho, decisões, medição, pela divisão da ISO/IEC/IEEE 15288 entre processos
técnicos e de gestão), com o `METODO.md` como o padrão atual desse grupo, e o C decide só essa fronteira →
[D-330](../../domain/decisions/D-330.md). `STD-metodo` tem `basis: [D-330]`; o campo `group` dos sistemas e a medida por
grupo vêm numa PR própria.

## Resumo
- **16 regras avaliadas.** 13 são regras de verdade e 3 não recusam nada. A #230 contou 2 casos assim; `generate-blocked`
  é o terceiro. `program-plan-block` é um parser, e a regra de verdade dele é `program.load`.
- **Proposta: seis rascunhos (A a F) em vez de 14 decisões, uma por regra.** O F, pedido por Daniel em 18/11 às 19:24, traz o esforço mais barato para o momento da decisão. O A (contrato dos registros) cobre 6 regras. O B
  (decidir, depois reportar) cobre 1. O C (o método de gestão) cobre 1. O D (regra dormente) cobre 2 sozinho e marca
  mais 3 que já têm base no A ou no B. O E (aposentadorias) cobre 6.
- **10 ficam:** 6 com o A, 1 com o B, 1 com o C e 2 só como dormentes (D). **6 se aposentam:** os 3 casos que não são
  recusa, as 2 regras de esforço e o modo de recusa do registro de regras. **8 têm o texto reescrito:** são as que
  ficaram com o texto da semente ou com a docstring da função.
- **Achado transversal:** o `tower/gate` pula o estágio `pr metadata` (`scripts/lib/verify_commit.py:37`). Com isso,
  4 das 16 regras e 10 já justificadas pela #230 aparecem como `blocking` no catálogo, mas nenhuma etapa viva roda essas
  checagens.
- **Três perguntas reais para Daniel**, no fim, cada uma com a minha recomendação. A 3 já tem resposta, e ela virou o F.

## Avaliação: o que cada regra é e faz
"Viva" quer dizer que alguma etapa do fluxo de hoje chama a checagem: os estágios do `tower/gate`, que são os de
`scripts/gate-check` linhas 60 a 75 menos o `pr metadata`, os testes que os `covers` selecionam ou o pre-push.
"Dormente" quer dizer que só a ferramentaria parada a chama: o gate da AWS, o trem, a caixa e a entrega da era Origin,
paradas segundo o AGENTS.md e a D-314.

| # | Regra (`STD-…`) | O que o código faz | Viva hoje? | Teste | Faz sentido? Dano sem ela | Caso ou princípio | Destino |
|---|---|---|---|---|---|---|---|
| 1 | `aws-tenant-isolation-proof-refusal` | `Tenant.refusal` (`scripts/lib/aws_tenant_isolation_proof.py:61`) chama a porta e devolve `(status, texto)`. A recusa que vale como PASS é a da porta, não a deste método | Não: é uma prova manual, ao vivo, da porta de jobs do gate da AWS, que está parado. Nenhum estágio a chama | `test_aws_tenant_isolation_proof.py` | Não é regra: nada é recusado. A propriedade, isolamento entre tenants, é da porta | — | Aposentar a regra (E). A função fica, com outro nome |
| 2 | `budgets-schema-errors` | `budgets.schema_errors` (`budgets.py:76`) valida a linha de base de orçamentos contra `contracts/budgets/baseline.v1.json`. É chamada por `budget_check.py:71` e na escrita (`budgets.py:88`) | Sim, no estágio `measurement checks` (`measurement_checks.py:106`, `gate-check:65`). Está ociosa: o arquivo `config/baselines/budgets.json` não existe e `check_baseline` devolve `[]` | `test_budgets.py:90` | Sim. Sem ela, uma linha de base malformada chegaria à comparação de regressão (D-069 item 14) e quebraria a etapa ou passaria em silêncio | Princípio: contrato antes do dado | A |
| 3 | `census-shape-errors` | `census._shape_errors` (`census.py:212`) valida o schema de um evento do censo e mais quatro invariantes que o schema não exprime: um `remove` não traz `entry`, um `add` traz, a forma tem de bater com a do censo e uma entrada de linha de base nunca vem vazia | Sim, em `measurement checks` (`census.check`, `census.py:254`). Está ociosa: não há nenhum `units/*/census.jsonl` | `test_census.py` testa a cadeia, a dobra e a posse. **Nenhum teste nomeia os quatro invariantes** | Sim. Sem ela, um evento malformado entra na dobra e o veredito do censo (D-063, D-064 a) fica errado | Princípio: contrato antes do dado | A, mais um teste para os invariantes |
| 4 | `lessons-vocabulary-errors` | `lessons.vocabulary_errors` (`lessons.py:86`) exige que `class`, `kind`, `owner`, `status` e `level` de uma lição venham das listas `lessons.*` do registro | Sim, no teste `lessons`, selecionado por `docs/process/lessons/*` (`test_lessons.py:180`, `check(ROOT)`). São 16 lições, nenhuma mudada desde 14/11 | Só pela árvore: nenhum teste recusa um vocabulário fora da lista | Sim. Sem ela, um valor fora do vocabulário entra no registro e nenhum leitor das listas o reconhece. O vocabulário fechado é um dado do registro (D-068) | Princípio: um vocabulário fechado mora no registro | A |
| 5 | `vendor-check-catalog-errors` | `vendor_check.catalog_errors` (`vendor_check.py:209`) checa o catálogo de fornecedores: os caminhos citados existem, todo site da linha de base é classificado, nenhuma classificação fica órfã, um `forbidden` não tem adaptador nem linha de base, um `slot` não tem adaptador | Sim, no `structure check` em toda PR (`vendor_check.py:261`, `structure.py:350-371`). São 9 fornecedores | `test_vendor_check.py:102`, `test_vendor_classification.py:51` | Sim. A irmã `shrink_errors` tem a D-069 item 7, e um catálogo incoerente faria essa checagem julgar sobre dado falso | Princípio: integridade referencial do dado que uma regra decidida lê | A |
| 6 | `retro-shape-errors` | `retro.shape_errors` (`retro.py:121`) recusa um log vazio, que não é UTF-8 ou, quando é transcrição, que não é JSONL do Claude Code. É chamada na entrada do armazém (`retro.py:156`) | Dormente. O armazém RETRO-API é da caixa e fica no gitignore. "Nothing reads `retro/` today" (`docs/units/RETRO-API/audit.md:52`), e nenhum hook da nuvem chama `scripts/retro` | `test_retro.py:205` | Sim, na fronteira de um armazém. Mas ela não julga mudança nenhuma: `applies_to: CHG` está errado | Princípio: contrato na fronteira | A + D. Reescrever `applies_to` |
| 7 | `program-plan-block` | `program.plan_block` (`program.py:50`) extrai o bloco cercado do `plan.md` e levanta erro quando ele falta. Quem julga o bloco contra `program.v1.json` e o grafo é `program.load` (`program.py:98-104`) | Dormente. `program.check` é do coordenador CO1, da era Origin, e nenhum estágio o roda sobre os programas reais. O teste `program` só carrega o `reach-1000-prs-per-day` (`test_program.py:16,40`). Os programas do método (`padrao-dev`, `vazao`, `gate-speed`) não têm `plan.md` | `test_program.py` | Em parte. O que vale proteger é o contrato do plano de um programa CO1. O parser em si não é regra | Princípio: contrato antes do dado | Reescrever para `program.load`, depois A + D |
| 8 | `generate-blocked` | `generate.blocked` (`generate.py:102`) diz por que um alvo de geração não roda (desligado, ou nada casa com `requires`). Os chamadores **pulam** o alvo (`generate.py:90,125`) | Sim, como isenção dentro do `generated drift` | `test_generate.py:167` | Não é regra: não recusa nada, só isenta. A regra é `STD-gate-generated-drift` | — | Aposentar a regra (E). A função fica, com outro nome |
| 9 | `forge-origin-refuse-remote` | `forge_origin.refuse_remote` (`forge_origin.py:79`) é a trava do adaptador do Origin: se o remoto git não é o repositório num host declarado do Origin, nenhum merge nem lock viaja | Dormente. O adaptador nasce só no fluxo do Origin (`forge_origin.py:133`). No preflight o teste é pulado quando o remoto é o GitHub (`forge_origin.py:109-111`) | `test_origin_remote.py:76` | Fazia sentido: um lock ou merge empurrado para outro forge é dano real na era Origin. Hoje o Origin é espelho de mão única (D-314) | Caso do adaptador. O princípio por trás é "um adaptador falha fechado fora do alvo declarado" | D. Aposenta-se junto com o adaptador do Origin |
| 10 | `decision-wait-errors` | `decision_wait.errors` (`decision_wait.py:91`) recusa uma PR cujo comentário espera o dono sem uma linha `Decision:` depois | Dormente. Só roda em `commit_check.check` (`commit_check.py:214`), dentro do `pr metadata`, que o `tower/gate` pula | `test_commit_check.py:165` | O princípio vale: o AGENTS.md diz "Act, don't ask" e trata como incidente qualquer outra parada para perguntar. A checagem por frase em comentário de PR é fraca e hoje não roda | Ordem de Daniel (26/10 21:29, 02/11), generalizável | B + D. Reescrever |
| 11 | `effort-errors` | `effort.errors` (`effort.py:74`) exige o bloco `## Cheapest useful effort`, com quatro campos e um dono humano no `Requirement` | Não: só a usa `body_errors` (#12). A metade que julgava os `plan.md` saiu pela D-292 | `test_structure_effort.py:52`, `test_pr_body.py:124` | Não hoje. Nasceu de uma ordem de 28/10 (`docs/padrao/v4/effort.md`), e o padrão v4 foi substituído pelo v8 e pelo método | Caso (o incidente WebKit de 28/10) | Aposentar (E) |
| 12 | `effort-body-errors` | `effort.body_errors` (`effort.py:128`) aplica a #11 ao corpo da PR | Dormente. `measurement_checks.py:119-120` roda no `pr metadata` (`gate-hooks/prereq.sh:19`, `gate_verdict.py:186`), e o `tower/gate` pula. **Nenhuma das 30 PRs de #202 a #231 tem o bloco**, e nenhum dano foi registrado | `test_structure_effort.py:126,160`, `test_pr_body.py:55` | Não. É um campo de formulário que ninguém preenche e nenhuma etapa cobra | Caso | Aposentar (E) |
| 13 | `rule-registry-refusals` | `rule_registry.refusals` (`rule_registry.py:529`) diz o que o modo `refuse` do registro de regras RULE-AUDIT recusaria | Não: `rules.check_mode` é `report`. O `refuse` nunca rodou, e `scripts/rule` não está no gate. O catálogo `rules.catalog` tem 1 registro | `test_rule_registry.py:251-257` | Não. A F1b fez do catálogo STD o registro de regras (`phases/F1.md:31-33`), e manter dois registros fere a D-069 item 1 | Caso (RULE-AUDIT, 28/10) | Aposentar o modo `refuse` (E). `discovered()` fica, porque o `model.py:489-494` lê |
| 14 | `structure-lane-errors` | `commit_check.lane_errors` (`commit_check.py:239`) recusa uma mudança que toca unidades de mais de uma lane, porque o trem não saberia a lane dela (`train_ownership.lane_of`, `:64`) | Dormente. Só roda em `pr_errors` (`commit_check.py:259`, `pr metadata`) e em `--pr-body` **com** `--base` (`:275`). O AGENTS.md manda rodar `--pr-body` sem base. Hoje há duas lanes: `engine-lane` com 61 unidades e `site-lane` com 1 | `test_commit_check.py:450-480` | Só para o trem: o único motivo dela é a lane ser indecidível para ele (`docs/units/GX21/audit.md:14-17`). Na fila de merge não há lane a decidir | Caso (GX-21, uma pré-checagem do trem) | D. Aposenta-se com o trem |
| 15 | `metodo` | É julgamento: o trabalho segue o `docs/padrao/METODO.md` (PDCA para programa e projeto, SDCA para processo e operação, retrospectiva em todo nível) | Viva como julgamento: o AGENTS.md manda segui-lo | — (`judgment`) | Sim: é o padrão de gestão. O que falta é o registro, não a razão | Decisão de Daniel de 02/11, nunca registrada como D-NNN | C |
| 16 | `gate-timing-report-eta-errors` | `gate_timing_report.eta_errors` (`gate_timing_report.py:79`) monta as linhas do erro da ETA do gate no relatório GX-25. "Erro" ali é erro de estimativa | Dormente. Lê `gate.started` e os veredictos do gate da era Origin | `test_gate_timing_report.py:64-72` | Não é regra: é um relatório | — | Aposentar a regra (E). A função fica, com outro nome |

### Achado transversal: o `pr metadata` não roda no `tower/gate`
`verify_commit.py:37` tem `SKIPPED = ('pr metadata',)`, com o comentário "reads the pull request on Origin; the GitHub
pull request is judged by its own reviewers". Mas não há etapa de revisão (D-055). Por isso não roda no fluxo vivo o
que só o `pr metadata` chama: das 16, `decision-wait-errors`, `effort-body-errors` e, pelo `pr_errors`,
`structure-lane-errors`; das 29 da #230, `STD-gate-pr-metadata` (que é `blocking` e tem a D-314 como base) e as regras
do `commit-check` sobre a PR (`plan`, `fixup`, `push`, `force-push`, `rebase`, `gate`, `pr`, `plan-completeness`). O
pre-push roda as suas próprias formas de três delas (`local_checks.py:91`, `:119`, `:136`). Isso fica fora das 16, mas
condiciona o rascunho D e a pergunta 1.

## Pesquisa: de onde vieram e o que a prática de referência faz
**Origem de cada uma.** As notas e as docstrings dão a origem. As de forma vêm de unidades que citaram itens da D-069
no cabeçalho do módulo sem que o item dissesse a regra: `budgets.py:1` cita o item 14, `census.py:1` cita D-063, D-064 (a)
e D-067, `lessons.py:1` cita os itens 4 e 9 (LR1), `vendor_check.py:1` cita o item 7 e `program.py:1` cita CO1. As de
processo vêm de ordens de Daniel que nunca viraram D-NNN: DECIDE, THEN REPORT (26/10 21:29, `decision_wait.py:1`),
esforço mais barato útil (28/10 13:55, `docs/padrao/v4/effort.md`), RETRO-API (28/10 20:00, `retro.py:2`), RULE-AUDIT
(28/10 16:52, `rule_registry.py:1`) e o método (02/11, `METODO.md:3`). Duas uma unidade definiu sozinha: GX-21 (lane
indecidível, `docs/units/GX21/retro.md:4`) e o adaptador do Origin (D-283 e D-300 fazem o adaptador, mas não a trava do
remoto). Três a semente pegou pelo nome: a regex de `rules.stop_patterns`, `^\s*def ([a-z_]*(errors|refus|reject|block)[a-z_]*)\(`
(`config/registry/rules.json`), casa com `refusal`, `eta_errors` e `blocked` sem que nada seja recusado.

**Por que a #230 não aceitou a D-069 para as de forma.** O critério dela é que o texto da decisão estabeleça a regra,
e um D-NNN no cabeçalho não basta. A D-069 item 2 diz "contracts are schema-first ... the gate checks compatibility" e
o item 3 diz "configuration ... typed, validated". Os dois tratam de compatibilidade e de valores do registro, não de
cada registro validado contra o seu contrato, nem dos invariantes que o schema não exprime. O critério está certo. A
lacuna é de enunciado, não de razão.

**A prática de referência.**
- *Validação por schema.* Ninguém decide schema por schema. O princípio é um só, contrato antes do dado, e cada
  validação é uma instância dele. Um registro de schemas, como o de eventos com Avro ou JSON Schema, aplica uma só
  política de compatibilidade a todos os assuntos. O Kubernetes valida todo recurso pelo schema OpenAPI do CRD na
  admissão, e os invariantes que o schema não exprime ficam em regras CEL (`x-kubernetes-validations`) ao lado do
  schema, não espalhados. "Parse, don't validate" (A. King, 2019) põe a recusa na fronteira de entrada. Num banco, a
  integridade referencial (chave estrangeira) é uma propriedade do modelo, não uma decisão por tabela.
- *Descoberta de regras.* Linters e analisadores (ESLint, Semgrep, Ruff) registram cada regra por id, explicitamente,
  e nunca a descobrem pelo nome de uma função. Achar por nome dá falso positivo, como os três casos acima.
- *Controle declarado e controle em operação.* Numa auditoria de controles (a declaração de aplicabilidade da ISO/IEC
  27001, o tipo II do SOC 2), um controle declarado que não opera é uma não conformidade. A eficácia do desenho e a
  eficácia da operação são avaliadas em separado. O catálogo STD que diz `blocking` para uma checagem que nenhuma
  etapa roda é esse caso.
- *Decidir sem esperar.* A doutrina de comando por intenção (Auftragstaktik) e a regra das decisões reversíveis, as
  "portas de duas vias" da carta de 2015 da Amazon, mandam quem está perto do problema decidir dentro da intenção e
  reportar. Para o dono fica só o que é irreversível ou de fora. É o que a lista fechada do AGENTS.md já diz.
- *Campos obrigatórios de PR.* Modelos de PR guiam. O que um gate cobra é só o que uma máquina decide, como o plano
  de commits, um fix-up ou uma mudança de gate sem decisão. Um campo de texto livre que se cobra vira texto de
  preenchimento, e o 0 de 30 mostra que aqui ele nem isso virou.

## Análise: o que elas realmente protegem
1. **A integridade dos registros que o motor lê para decidir** (2, 3, 4, 5, 6 e 7). Todas dizem a mesma coisa: um
   dado que alguém vai ler para julgar segue o seu contrato, que é o schema mais os invariantes que o schema não diz,
   inclusive referências que precisam existir. A razão é uma só, e por isso a decisão também deve ser uma.
2. **Que o dono não seja o gargalo** (10). É uma ordem viva de Daniel (AGENTS.md, "Act, don't ask"; D-294 trata do
   julgamento, não da espera). Falta o registro. A checagem atual (frases em comentários de PR) é só uma das
   evidências possíveis e hoje não roda.
3. **O método de gestão** (15). É uma decisão tomada e escrita (`METODO.md:3`) que não ganhou número.
4. **Travas da ferramentaria parada** (9, 14, e as partes dormentes de 6, 7 e 10). O dano que elas evitam era real
   no Origin e no trem e não existe na fila de merge. Aposentá-las agora seria decidir também o futuro da
   ferramentaria da era Origin, que o AGENTS.md mantém na árvore. Justificá-las agora seria inventar uma razão de
   enforcement para o que não é enforced. A saída honesta é um estado próprio: dormente.
5. **O que não é regra** (1, 8 e 16) e **o que perdeu a razão** (11, 12 e 13). A causa dos três primeiros é de classe
   (D-069 item 9): a descoberta por nome. Tirar só a regra faria `rule_findings` (`model.py:502-505`) avisar de novo
   "a refusal with no rule". Os outros três têm o mesmo padrão da D-298 (uma regra que impõe algo que saiu) e da D-292
   (um controle antigo que não protege mais nada é removido, não contornado).

Uma decisão para cada grupo, e não para cada regra. A regra 9 sozinha caberia num princípio "o adaptador falha fechado
fora do alvo declarado". Mas entre as 16 só ela é instância desse princípio, e ela está dormente. Uma decisão para uma
regra que não opera seria exatamente o que o pedido quer evitar, então ela fica só com o D.

## Solução: os rascunhos
O texto de cada rascunho vai em inglês, como os registros `docs/domain/decisions/D-*.md` (enunciado, razão, prova,
caminho de volta). Nenhum tem número. Os números vêm de `scripts/decision-record` só depois que Daniel aprovar.

### D-rascunho-A: o contrato dos registros
> **Every record the engine reads to decide conforms to its contract, and the module that owns the record refuses one
> that does not (D-069 items 2 and 3 stated as a rule of records; PADRAO-DEV, the rules no decision states, 18/11/2026,
> awaiting Daniel).** A record is what the engine writes and later reads to judge: a registry value, a baseline, a
> unit's census event, a lesson, a catalog, a program's plan block, a log a store receives. Its contract is the JSON
> Schema that declares it plus the invariants that schema language cannot state: a field present exactly when another
> holds, a closed vocabulary kept as a registry list (D-068), a path or name it cites that must exist. Those invariants
> are written once, in the module that owns the record, next to the schema they complete, and a test names each one.
> The owner refuses on write and the reader refuses on read; nothing is judged on a record that fails its contract. One
> decision for the class, never one per schema: a new record type gets its contract and its check under this rule, and
> its rule in config/standard/rules/ takes this decision as its basis. Proof: scripts/tests/test_model.py. Revert path:
> a later decision that supersedes this one; its rules return to no basis.

- **Razão:** as seis checagens protegem a mesma coisa, e a prática de referência trata isso como um princípio só.
- **Cobre:** `budgets-schema-errors`, `census-shape-errors`, `lessons-vocabulary-errors`,
  `vendor-check-catalog-errors`, `retro-shape-errors` e `program-plan-block` (este reescrito).
- **Se aceito:**
  - Os seis arquivos ganham `basis: [<A>]`.
  - Os enunciados reescritos ficam assim:
    - budgets: "The budgets baseline (budgets.baseline_path) validates against contracts/budgets/baseline.v1.json."
    - census: "Each event of a unit's census record validates against contracts/units/census.v1.json, and a remove
      carries no entry, an add carries one shaped as its census, a baseline entry is never empty."
    - lessons: "A lesson's class, kind, owner, status and level are values of the lessons.* registry lists."
    - vendor catalog: "The vendor catalog is coherent: every path it names exists, every baseline site is classified
      and no classification is orphaned, a forbidden vendor has no adapter or baseline, a slot has no adapter."
    - retro: "A log the retro store receives is non-empty UTF-8, and a transcript is Claude Code JSONL."
    - program: "A CO1 program's plan.md carries the program.v1 block, valid and acyclic."
  - Os `applies_to` ganham o tipo do objeto julgado: `MEAS`, `UNIT`, `LESSON`, `CFG`, `DATA` (este no lugar de `CHG`)
    e `WORK`.
  - O `check.ref` do programa vira `scripts/lib/program.py:load`.
  - Uma PR de teste nomeia os quatro invariantes do censo, que hoje não têm teste.
  - Alternativa equivalente para o censo: levar os invariantes para o schema (`if`/`then` no `census.v2.json`, pela via
    de expandir e depois contrair). Isso troca código por contrato, mas custa uma versão nova. Recomendo o teste agora.

### D-rascunho-B: decidir, depois reportar
> **Decide, then report: no session stops to wait for the owner outside the closed list (Daniel 26/10/2026 21:29 and
> 02/11/2026 23:19 BRT, I-ddaca17c; until now an order in AGENTS.md and in scripts/lib/decision_wait.py, never a
> decision; awaiting Daniel).** A next step that follows from the stated goals is executed and reported, never asked.
> A choice the goals do not settle is taken with the reversible option, recorded with its revert path and reported.
> The owner's hand is needed only for a login, a credential, money, other people or quota; any other stop to ask is
> an incident (scripts/incident open owner-stop). D-294 is unchanged: it governs how the session judges a request,
> this decision that it never waits for one. Its checks are the Stop hook scripts/hooks/cycle-stop and decision_wait (a
> PR comment that waits on the owner with no later Decision line). Proof: scripts/tests/test_commit_check.py
> (test_refuses_a_comment_that_waits_on_the_owner_without_a_later_decision). Revert path: a later decision that
> supersedes this one.

- **Razão:** é uma ordem viva, citada no AGENTS.md e no código, que só não tem registro. A doutrina de referência
  (decidir dentro da intenção, deixar as portas de duas vias com quem está perto) diz a mesma coisa.
- **Cobre:** `decision-wait-errors`.
- **Se aceito:**
  - A regra ganha `basis: [<B>]`.
  - Novo enunciado: "A PR comment that waits on the owner is followed by a Decision line."
  - O estado dela fica `dormant` (D) enquanto o `pr metadata` não rodar.
  - A mensagem de `decision_wait.py:98-101` passa a citar a decisão em vez da data solta.

### D-rascunho-C: o método de gestão
> **The management method of docs/padrao/METODO.md is the engine's standard of management (Daniel 02/11/2026, written
> 03/11; recorded 18/11/2026, awaiting Daniel).** Four levels, each declaring its nature, its closing criterion and its
> owner: program and project are managed by improvement (PDCA), process and operation by routine (SDCA), and the review
> step is called retrospective at every level. Where it differs from Padrão v7/v8 or from the unit flow of D-077, the
> method prevails (D-292 already dropped mandatory intake). A program of the method carries the documents of its steps
> (evaluation, research, analysis, solution, phases, retrospective); the CO1 layout of coordinator.program_files (brief,
> audit, plan, retro) stays only for the coordinator's programs. Proof: scripts/tests/test_model.py (STD-metodo has this
> basis). Revert path: a later decision that supersedes this one.

- **Razão:** a decisão existe (`METODO.md:3`, AGENTS.md "Read first") e só falta o número. A D-069 item 10 pede a
  citação literal de Daniel para confirmar, e é por isso que este rascunho vai a ele (pergunta 2).
- **Cobre:** `metodo`.
- **Se aceito:**
  - `STD-metodo` ganha `basis: [<C>]` e continua `draft`/`judgment`.
  - A divergência entre `coordinator.program_files` e os programas do método deixa de ser um conflito sem dono: o CO1
    fica restrito aos programas do coordenador, dormentes pelo D.

### D-rascunho-D: a regra dormente
> **A rule of the standard says what the live flow enforces; a rule whose check runs only in tooling a decision stopped
> is dormant (PADRAO-DEV, 18/11/2026, awaiting Daniel).** contracts/model/rule.v1.json gains the state dormant (an
> additive enum value, expand only) and the field dormant_by, the decision that stopped the tooling (D-314: the AWS gate,
> the train, the box, the Origin-era delivery). A dormant rule keeps its file, its code and its test, which the full
> suite still runs after every merge; it counts in no enforcement measure (the model's conformance, the verified chain);
> it needs no basis while dormant, and the decision that brings its tooling back gives it one or retires it. A rule
> marked blocking is one whose check tower/gate or the pre-push check runs; scripts/model refuses a blocking gate-stage
> rule whose stage verify_commit skips. Proof: scripts/tests/test_model.py. Revert path: a later decision that
> supersedes this one; the dormant rules return to their previous state.

- **Razão:** o catálogo deve contar a verdade sobre o que opera, como na separação entre a eficácia do desenho e a da
  operação. Justificar uma trava que não opera seria inventar razão, e aposentá-la seria decidir a sorte da
  ferramentaria da era Origin pela porta dos fundos.
- **Cobre sozinho:** `forge-origin-refuse-remote` e `structure-lane-errors`. **Marca também:** `retro-shape-errors` e
  `program-plan-block` (base A) e `decision-wait-errors` (base B).
- **Se aceito:**
  - O `rule.v1.json` ganha `dormant` e `dormant_by`.
  - O `model.py` (`rule_findings`, `:502-526`) deixa de avisar falta de base para as regras dormentes, e a medida as
    exclui.
  - Os cinco arquivos ficam `state: dormant`, `dormant_by: D-314`.
  - Novo enunciado do forge: "The Origin adapter acts only on its repository on a declared Origin git host."
  - Fora das 16, pela pergunta 1, `STD-gate-pr-metadata` e as regras do `commit-check` sobre a PR também passam a
    dormentes, salvo se o `pr metadata` voltar.

### D-rascunho-E: as aposentadorias
> **Six seeded rules retire: three seeds that refuse nothing, the cheapest-useful-effort check, and the refuse mode of
> the RULE-AUDIT rule register (PADRAO-DEV, the rules no decision states, 18/11/2026, awaiting Daniel; a gate change
> under this decision).** Tenant.refusal, gate_timing_report.eta_errors and generate.blocked were matched by name by
> rules.stop_patterns; each is renamed for what it does (attempt, eta_misses, skip_reason) so the discovery no longer
> finds it, and keeps its behavior and its test. The effort block of docs/padrao/v4/effort.md (Daniel 28/10) lost its
> plan half by D-292, and its PR-body half runs only in pr metadata, which tower/gate skips; 0 of the 30 PRs #202 to #231
> carried it and no harm was recorded, so the check, its registry owner effort and its tests leave, and
> docs/padrao/v4/effort.md stays as history. The rule register's refuse mode never ran (rules.check_mode is report) and
> the standard's catalog of rules (D-317, F1b) is now the one register (D-069 item 1); refusals(), the refuse mode and
> their test leave, and discovered() stays for scripts/model. Proof: scripts/tests/test_model.py (no refusal without a
> rule, and none of the six). Revert path: revert the PR.

- **Razão:** três casos não são regra. Os outros três perderam a razão, no padrão da D-298 e da D-292. A troca de nome
  corrige a classe (D-069 item 9) sem criar uma lista de exceções que só cresce.
- **Cobre:** `aws-tenant-isolation-proof-refusal`, `gate-timing-report-eta-errors`, `generate-blocked`, `effort-errors`,
  `effort-body-errors` e `rule-registry-refusals`.
- **Se aceito:** o detalhe está na lista abaixo. Como a mudança toca `scripts/lib/gate_timing_report.py` e
  `scripts/lib/structure.py`, o `commit-check` (`gate_errors`) exige que a PR cite o D-NNN aprovado. Por isso o E vem
  antes da PR.

### D-rascunho-F: o esforço mais barato que resolve, na hora de decidir
Daniel respondeu à pergunta 3 em 18/11, às 19:24 BRT. Ele concorda que o "esforço mais barato útil" não é uma regra que barra PR, mas quer que a IA pense nisso **logo de saída**, sempre que for decidir. A preocupação dele: hoje nada garante que essa pergunta seja feita no momento da decisão. Uma checagem que ninguém preenche não resolve, e confiar só na D-294 e nas guardas de custo também pode não bastar.

A própria árvore já mostra que ele tem razão. O bloco de esforço era um campo a preencher, e 0 dos 30 PRs de #202 a #231 o trazia. Um formulário fica longe do momento em que o caminho é escolhido: ele é preenchido depois, quando já não muda nada. Por isso a pergunta precisa estar onde a escolha acontece, e precisa deixar um rastro que alguém lê.

> **Every choice of how to solve a problem starts from the cheapest effort that solves it (Daniel, 18/11/2026 19:24
> BRT, through the Torre; awaiting his approval).** Before a session chooses how to do something (a design, a fix, a
> delegation, an AWS change), it names the cheapest path that would solve it and takes a costlier one only for a
> reason the measure or the risk gives, which it states in one line where the choice is recorded: the commit
> message or PR body that carries it, or the brief that delegates it. Three places carry it, none of them a field
> that blocks a PR:
> (1) AGENTS.md's judgment rules, read at the start of every session, state it next to D-294.
> (2) Every brief to a subagent names the cheapest acceptable path and what is out of scope, because a delegated task
> spends most of the effort.
> (3) The retrospective samples merged PRs and asks of each "was there a clearly cheaper path that solved it?"; the
> share of yes is a measure, so the rule is checked by its effect, not by a filled field.
> Proof: the measure's reader and its test (scripts/model, the retrospective sample). Revert path: a later decision
> that removes it.

- **Razão:** a pergunta passa a estar no contexto de toda decisão, pelo AGENTS.md e pelos briefs, e deixa um rastro curto onde a decisão já é registrada. Ela é conferida pelo efeito, na retrospectiva, e não por um campo preenchido.
  - O que não funciona e fica de fora: um campo obrigatório no PR, como o bloco de esforço, e uma regra `judgment` que nada mede.
- **Cobre:** nenhuma das 16 regras. Ela entra no lugar de `effort-errors` e `effort-body-errors`, que o E aposenta.
- **Se aceito:**
  - uma linha nas regras de julgamento do AGENTS.md, junto da D-294;
  - uma linha no modelo de brief que as sessões usam para delegar;
  - a amostra da retrospectiva, com a medida "parcela de PRs com um caminho claramente mais barato", lida pelo `scripts/model` com o seu teste.
  - Nenhum gate muda.
- **O que ainda está em aberto:** o tamanho da amostra e a meta da medida. Proposta: 10 PRs por retrospectiva e a meta abaixo de 10%, revista depois de três retrospectivas.

## Aposentadorias e reescritas
**Aposentar (6):**
1. `STD-aws-tenant-isolation-proof-refusal`: sai o arquivo da regra. `Tenant.refusal` vira `attempt`
   (`aws_tenant_isolation_proof.py:61` e os chamadores). O teste fica.
2. `STD-gate-timing-report-eta-errors`: sai o arquivo. `eta_errors` vira `eta_misses` (`gate_timing_report.py:79,156`,
   `test_gate_timing_report.py:64-72`). O teste fica, com o nome novo.
3. `STD-generate-blocked`: sai o arquivo. `blocked` vira `skip_reason` (`generate.py:90,102,125,202,210,216`). Os
   testes ficam. A regra que governa é `STD-gate-generated-drift`.
4. `STD-effort-errors` e 5. `STD-effort-body-errors`: saem os dois arquivos. Também saem `scripts/lib/effort.py`,
   `scripts/lib/effort_owners.py`, `config/registry/effort.json` e `config/registry/effort/` (com o tipo gerado
   regenerado), o subcomando `body` de `measurement_checks.py` (linhas 10, 119-120 e 134), a chamada em
   `gate-hooks/prereq.sh:19` e em `gate_verdict.py:186`, `pr_body.effort_block` (`pr_body.py:19,41-43`) e os
   comentários de `structure.py:550,572`. Os testes saem: `test_structure_effort.py` inteiro e as partes de esforço de
   `test_pr_body.py:55,124`, com os `covers`. `docs/padrao/v4/effort.md` fica, como histórico.
6. `STD-rule-registry-refusals`: sai o arquivo. Saem também `rule_registry.refusals` (`:529-543`), o modo `REFUSE` de
   `check()`, a chave `rules.check_mode`, `scripts/rule check --mode` e `test_rule_registry.py:174-178,251-257`. Ficam
   `discovered()` (lido em `model.py:489-494`) e o resto do registro, cujo destino (dobrar os campos do RULE-AUDIT nas
   PROP/TAIL da F1c) é assunto da fase, não deste documento.

**Reescrever (8), além da base:** os enunciados e campos de `budgets-schema-errors`, `census-shape-errors`,
`lessons-vocabulary-errors`, `vendor-check-catalog-errors`, `retro-shape-errors` (`applies_to` `DATA`),
`program-plan-block` (`ref` passa a `program.py:load`), `decision-wait-errors` e `forge-origin-refuse-remote`, como
está no A, no B e no D. Em toda regra que ficar, a `note` troca "No basis: ..." por "Basis: ...", ou por "Dormant: ..."
no caso das dormentes.

## Perguntas abertas para Daniel
1. **O `pr metadata` volta ao `tower/gate`?** As regras de disciplina de commit (D-025, D-070, D-022) e o
   `decision-wait` estão no catálogo como `blocking`, mas o gate vivo as pula porque o estágio lia a PR no Origin.
   Opções: (a) um estágio que lê a PR do GitHub pelo `gh` e roda as checagens que a máquina decide (plano, fix-up,
   mudança de gate sem decisão, espera pelo dono); (b) declarar todas dormentes (D). **Recomendação: (a)**, porque
   elas são baratas, já existem e protegem o histórico que o merge queue não protege. O custo é um estágio de gate,
   que precisa de decisão (D-025).
2. **O método e o "decidir, depois reportar" se registram com a sua citação literal?** A D-069 item 10 pede uma
   citação literal sua para confirmar. Os rascunhos C e B registram ordens que você já deu (02/11, e 26/10 e 02/11).
   **Recomendação:** confirmar os dois com uma frase. Sem isso, as duas regras continuam sem base, mas sem dano, porque
   o AGENTS.md já carrega as duas ordens.
3. **O "esforço mais barato útil" sobrevive como princípio de julgamento?** O E aposenta a checagem, e a pergunta
   ("essa ação cara precisa acontecer, e para quem?") poderia continuar como uma regra `judgment`. **Recomendação: não
   criar.** A D-294 (o julgamento da sessão) e as guardas de custo da SEMENTE §4 já cobrem isso, e uma regra de
   julgamento que nada mede repete o caso do campo que ninguém preenche.
   **Resposta de Daniel (18/11, 19:24 BRT):** não é uma regra que barra PR, mas a IA deve pensar no esforço mais barato
   logo de saída, sempre que decidir, e ele não quer depender só da D-294 nem das guardas de custo. A proposta está no
   **D-rascunho-F**: a pergunta fica onde a decisão acontece (o AGENTS.md e os briefs), com uma linha de rastro onde a
   escolha é registrada, e é conferida pelo efeito, numa amostra da retrospectiva.

O que não é pergunta, porque a escolha reversível já está tomada: dormente em vez de aposentar para as travas da era
Origin; troca de nome em vez de lista de exceções para os casos que não recusam; teste em vez de schema novo para o
censo.

## Verificação
- `scripts/structure-check --base origin/main`: 0 erros.
- `scripts/commit-check --local`: 0 recusas.
- Os números deste documento vêm de leituras de `main` em `97cd769`: os arquivos e as linhas citadas,
  `config/registry/rules.json`, `units/*/unit.json` e as 30 PRs fechadas de #202 a #231 lidas pela API do GitHub.
