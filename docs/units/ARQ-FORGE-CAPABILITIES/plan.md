# ARQ-FORGE-CAPABILITIES — plan

Entradas lidas, nesta ordem: [audit.md](audit.md), [research.md](research.md), [intake.md](intake.md), [padrão de auditoria e plano](../../padrao/v8/audit-and-plan.md), [template](../../process/templates/plan.md) e [plano da ARQ-SISTEMA](../ARQ-SISTEMA/plan.md). As contagens, os achados e as raízes abaixo pertencem exclusivamente à auditoria desta unidade; não houve nova medição. Este é desenho proposto para aprovação de Daniel, não execução.

A intenção é tornar explícita a compatibilidade das operações da porta, impedindo que um fluxo aceite em silêncio um adaptador que não atende, e explicar a permanência dos acessos externos. A decisão herdada R3 → A1 da ARQ-SISTEMA era remendo com Follow-up nesta unidade; não constitui aprovação antecipada de A2 nem de sua forma. A pesquisa distingue seleção, conformidade estrutural e comportamento, a partir de pluggy, abc e stevedore; nenhuma dessas referências determina ferramenta, schema ou adaptador.

O orçamento se ancora em **R2**: é a maior redução demonstrável de reconstrução do requisito neste recorte, porque reúne a demanda hoje dispersa em 18 operações, 38 sites e 14 arquivos e a confronta com o contrato que deixa 13 operações de fora. A concentração de `change` em 12 sites de 7 consumidores torna insuficiente ampliar uma lista sem ligá-la a quem chama. Essa é prioridade pelo alcance observado, não comparação causal de produtividade: não há medição causal de minutos por raiz nem prova de economia global.

## Alternativas

Custos são estimativas de planejamento em minutos de sessão ativa, incluindo provas locais, não medições da auditoria. Quota estimada igual aos minutos ativos, sem conversão em tokens. Não há ferramenta nova, serviço pago ou chamada remota obrigatória. Degraus são os da escada da pesquisa: 1 observado, 2 ideal separado, 3 recusa executável. Os números de custo abaixo são propostas de orçamento, não novos achados.

Cada faixa cobre apenas a alternativa daquela raiz; R1 fornece a fronteira e R2 fornece a exigência que ela consulta. A soma escolhida não presume desconto por compartilhamento. Presença de método não prova comportamento equivalente, e os contratos propostos não certificam operação remota.

### R1 — A fronteira aceita qualquer superfície e só descobre a incompatibilidade na chamada

Classe herdada: mecanismo faltando. Achados 2 e 6: `_operation` descobre a ausência tarde, `change` atravessa diretamente e `RoutingAdapter` encaminha qualquer nome.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Registrar matriz operação × consumidor × adaptador com limites de prova | remendo | não; a fronteira continua aceitando objeto incompatível e depende da consulta humana | 25–40 min; quota igual | Retirar vista documental | Matriz envelhecer ou parecer autorização de seleção | 1 |
| A2 Declarar operações atendidas e confrontá-las com as exigidas na construção do fluxo, incluindo `change` e roteamento | corrige a classe | sim, se toda construção do recorte passar pela conferência e identificar o adaptador responsável | 100–150 min; quota igual | Reverter conferência e declarações juntas, preservando seleção | Desvio direto ou declaração inexata produzir falsa compatibilidade | 3 |
| A3 Separar portas de diário, PR, status e coordenação, com contratos menores por fluxo | redesenho | sim, se consumidores migrarem e não restar passagem irrestrita ao adaptador | 200–300 min; quota igual | Restaurar fronteira por consumidor durante migração | Multiplicar interfaces antes de demonstrar necessidade e concluir migração | 3 |

A2 não exige a superfície inteira de um adaptador para cada fluxo. A diferença entre 24 métodos públicos no GitHub e 9 na Origin, com 16 exclusivos do primeiro e `status_channel` exclusivo da segunda, contextualiza capacidade; não define requisito universal.

O diagnóstico proposto distingue ausência exigida e ausência opcional, sem transformar `the RoutingAdapter has no ...` em atribuição ao fornecedor errado. Recusar antes do uso deve alcançar também os percursos hoje absorvidos em `pulls=None` e `overlap: skipped`, sem proibir degradação explicitamente opcional.

### R2 — Nenhum fluxo declara as operações que exige, e o contrato verificado é o subconjunto que os dois adaptadores já implementam

Classe herdada: regra faltando. Achados 3, 5 e 9: o contrato de 8 operações não representa a demanda dos consumidores e inclui diário; sua interseção não certifica um fluxo composto.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Ampliar à mão o contrato GitHub para as 18 operações censadas | remendo | não; cobre a fotografia, mas nenhum consumidor declara obrigação nem impede divergência futura | 40–65 min; quota igual | Reverter extensão dos casos | Confundir cobertura nominal com exigência de todo fluxo | 1 |
| A2 Derivar dos consumidores a declaração de exigências e recusar cobertura contratual inferior à exigência declarada | corrige a classe | sim, se chamadas diretas e dependências do papel integrarem a declaração e sua conferência | 120–180 min; quota igual | Reverter regra e declaração juntas, preservando provas anteriores | Declaração omitir percurso dinâmico ou ramo condicional | 3 |
| A3 Gerar contratos das declarações e recusar fluxo que chame fora deles | redesenho | sim, se a análise cobrir os percursos reais sem tomar o censo estático como teto | 210–320 min; quota igual | Retomar contratos manuais e retirar geração conjuntamente | Gerador repetir a omissão de sua própria entrada e aparentar prova independente | 3 |

A2 aproveita a separação de especificação e implementação da pesquisa sem introduzir pluggy ou uma hierarquia abc. Exigência disponível, exigência condicional e comportamento comprovado permanecem distintos; o formato da declaração será submetido com a decisão de execução, não fixado como schema por este plano.

O trem alcança 8 nomes: `lock`, `unlock`, `change`, `open_changes`, `read`, `merge`, `approvals` e `calls` opcional. `read` é diário; `calls` é contabilidade. `approvals` está morto no caminho da configuração auditada, com 47/47 manifestos sem `lane` e 0 com `contract`; isso não autoriza removê-lo do requisito condicional nem afirmar que nunca será chamado.

### R3 — A coordenação de papel (lock) e a contabilidade de chamadas moram no adaptador de forja

Classe herdada: arquitetura/desenho. Achados 4 e 6: o papel adquire `lock` antes da fila; a ausência impede o percurso mesmo quando suas operações de PR cabem na superfície disponível.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Manter `lock`/`unlock` na porta e declará-los como exigência herdada do papel, distinguindo `calls` opcional | remendo | não; explicita a dependência e sua recusa, mas coordenação e contabilidade continuam na forja | 25–40 min; quota igual | Retirar documentação específica sem migrar estado | Declaração ser confundida com separação efetiva de responsabilidades | 2 |
| A2 Transferir coordenação e contabilidade para mecanismos próprios do motor, preservando garantias de exclusão e medição | corrige a classe | sim, se a migração preservar aquisição, renovação, liberação e interpretação da contagem | 160–240 min; quota igual | Restaurar consumidores e mecanismo anterior em conjunto | Alterar exclusão entre papéis ou a autoridade do estado sem prova suficiente | 3 |
| A3 Migrar consumidores para portas distintas de diário, PR, coordenação e telemetria | redesenho | sim, se a separação não esconder a dependência em outra fachada e concluir a migração | 240–360 min; quota igual | Reverter migração por papel com compatibilidade explícita | Ampliar arquitetura e semântica operacional além do diagnóstico desta unidade | 3 |

A2 e A3 demandam desenho próprio da coordenação; a auditoria demonstrou a mistura, não mediu a segurança de um mecanismo substituto. Antecipar a recusa por R1/R2 é útil sem atribuir a este plano autorização de transferir estado, selecionar outro adaptador ou mudar a fonte da verdade.

### R4 — O baseline trata treze acessos de naturezas distintas como uma lista única que só encolhe

Classe herdada: regra faltando. Achado 7: `vendor_check.py:134-151,167-184` protege contra crescimento, mas não distingue razão de permanência. As 13 entradas não são dívida homogênea.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Anotar a natureza de cada entrada no próprio baseline | remendo | não; a classificação continua opcional e o verificador só compara conjuntos | 25–40 min; quota igual | Retirar anotações | Razões envelhecerem sem recusa ou serem tratadas como licença permanente | 2 |
| A2 Classificar cada entrada por natureza e razão de permanência, recusando ausência de ambas e preservando a regra de não crescimento | corrige a classe | sim para a falta de classificação; não promete remover dependências externas | 60–90 min; quota igual | Reverter regra e representação conjuntamente, mantendo baseline anterior | Aceitar justificativa vazia ou classificar import como requisição remota | 3 |
| A3 Expor na porta os dados ausentes e separar hospedagem, sonda e inicialização em lista própria | redesenho | sim, se cada migração preservar a forma dos dados e evitar o ciclo de credencial | 140–220 min; quota igual | Restaurar consultas e listas por entrada migrada | Ampliar a porta por quantidade de exceções sem demonstrar necessidade por consumidor | 3 |

A2 mantém distintas hospedagem de artefato, sonda de credencial, URL de origem, listagem histórica, dados omitidos pela forma da porta, versão de CLI, import de shim, identidade antes da porta e body/files. Não trata import como REST, nem exige que a sonda atravesse o store que depende dela.

O achado 8 fica explícito como limite do baseline: `forge_events.py:285` fixa GitHub em `board_adapter`; `config.py:321-334,341` constrói e inspeciona adaptador fora da seleção principal. Esses caminhos não entram nas 13 entradas. R1/R2 devem conferir sua construção específica sem trocar sua seleção; R4 não promete que classificar o baseline elimine esses caminhos.

## Escolha

- R1 → A2: antecipa a incompatibilidade observada sem multiplicar portas; inclui `change`, roteador e percursos diretos, com reversão conjunta. A1 conserva a descoberta tardia; A3 amplia migração sem ganho medido que a justifique.
- R2 → A2: ancora o orçamento na demanda dispersa e nas 13 operações fora do contrato; une exigência declarada e cobertura sem gerar um sistema novo de contratos. A1 envelhece sem vínculo; A3 exige alcance de análise que o censo, reconhecidamente piso, não prova.
- R3 → A1: torna explícita a barreira anterior à fila e separa obrigação de medidor opcional, sem alterar coordenação cujo substituto não foi auditado. Follow-up: unidade proposta ARQ-ENGINE-COORDINATION, ainda não aberta, para conserto de classe A2 com auditoria das garantias de coordenação e contabilidade.
- R4 → A2: acrescenta significado verificável às 13 entradas sem equiparar distribuição, inicialização e tráfego de forja; conserva a proteção existente. A1 mantém classificação facultativa; A3 antecipa extensões de dados antes da análise de migração por consumidor.

Orçamento escolhido: 305–460 minutos ativos, soma das faixas escolhidas; quota estimada igual aos minutos ativos, dinheiro incremental zero. São três correções de classe e um remendo, sem desconto presumido entre R1 e R2. A ordem é explicitar exigências e o limite R3, implantar R1 ligado a R2, e classificar R4 antes da consolidação das provas. Duração do gate final será registrada separadamente, não inventada como medição nem economia causal.

## Commits

Grafo futuro, **não executado nesta PR documental**: C1 → C2 → C3 → C5 e C1 → C4 → C5. C3 e C4 podem ser preparados em paralelo; não compartilham arquivos possuídos. Caminhos novos estão marcados como **novo proposto**, sem afirmar existência na base. Cada produto inclui suas provas; antes de código, C1 registra a decisão aprovada, com identificador reservado na execução.

| Commit | Produto e dependência | Arquivos possuídos |
|---|---|---|
| C1 | Exigências derivadas dos consumidores, distinção de diário/forja e limite R3; decisão e base de R2 | Novo proposto `scripts/lib/forge_requirements.py`; novo proposto `scripts/tests/forge_events/test_forge_requirements.py`; novo proposto `docs/architecture/FORGE-COMPATIBILITY.md`; registro de decisão a reservar e sua geração em `docs/domain/DECISIONS.md` |
| C2 | R1: operações atendidas, recusa na construção, `change`, roteador e construções específicas; depende C1 | `scripts/lib/forge_events.py`, `scripts/lib/forge_github.py`, `scripts/lib/forge_origin.py`, `scripts/lib/config.py`; novo proposto `scripts/tests/forge_events/test_forge_capabilities.py` |
| C3 | R2/R3: consumidores vinculados à exigência, guardas sem silêncio de incompatibilidade obrigatória e contrato com cobertura conferida; depende C2 | `scripts/lib/engine_role.py`, `scripts/lib/train.py`, `scripts/lib/flow_check.py`, `scripts/lib/prepush.py`, `scripts/lib/gate_report.py`, `scripts/lib/gate_status.py`; `scripts/tests/forge_events/test_forge_contract.py`; novo proposto `scripts/tests/forge_events/test_forge_consumers.py` |
| C4 | R4: natureza e permanência verificáveis sem remover entradas por contagem; depende C1 | `scripts/lib/vendor_check.py`, `scripts/lib/adapters/engine-vendors.json`; novo proposto `scripts/tests/test_vendor_classification.py` |
| C5 | Consolidar prova do recorte, limites e retro após C3/C4 | Novo proposto `scripts/tests/forge_events/test_forge_flow_compatibility.py`; novo proposto `docs/units/ARQ-FORGE-CAPABILITIES/retro.md`; manifesto existente de covers de `forge-events`, a conferir antes de editar |

A declaração cobre os consumidores censados, inclusive dependências compostas; consumidor não editado deve ter vínculo demonstrado pelas provas de C3, não presumido por nome. Se isso exigir outros arquivos de produção, revisar o plano e a posse antes da execução. Ajuste cruzado serializa dependências; não se distribui o mesmo arquivo entre commits paralelos.

## Premises

Premises: none

Não se adota premissa para trocar adaptador, mexer na fonte da verdade ou atribuir duração causal às raízes. Os custos são estimativas de planejamento, e o universo censado não é promessa sobre chamadas dinâmicas ou execução remota. Qualquer proposta que altere escopo, dinheiro, produção ou fonte da verdade é CRITICAL e exige revisão de Daniel; este desenho não autoriza selecionar Origin, ligá-lo em produção ou executar migração de coordenação.

## Tests

- C1: novo proposto `scripts/tests/forge_events/test_forge_requirements.py`, com conferência contra os consumidores identificados no audit. Prova composição de exigências obrigatórias, condicionais e opcionais, incluindo o papel; não prova completude de chamadas dinâmicas nem comportamento remoto.
- C2: novo proposto `scripts/tests/forge_events/test_forge_capabilities.py`, com dublês de superfície parcial, falta de `change`, roteamento e construção de board/store. Prova recusa antes da operação e diagnóstico do adaptador responsável, sem alterar seleção; não prova equivalência semântica ou disponibilidade de fornecedor.
- C3: `scripts/tests/forge_events/test_forge_contract.py` e novo proposto `scripts/tests/forge_events/test_forge_consumers.py`. Provar que exigência sem cobertura é recusada, inclusive chamada direta, e que ausência obrigatória não vira `pulls=None` ou `overlap: skipped`; preservar ausência explicitamente opcional. Exercitar `approvals` em ramo condicional por fixture. Não prova sua execução na configuração auditada nem conserta a raiz R3.
- C4: novo proposto `scripts/tests/test_vendor_classification.py`, com entradas sem classe, sem razão, crescimento indevido e razões distintas válidas. Prova recusa de classificação incompleta e preservação da monotonicidade; não prova que justificativa textual seja verdadeira nem que acesso externo foi eliminado.
- C5: novo proposto `scripts/tests/forge_events/test_forge_flow_compatibility.py` e `scripts/run test forge-events`, apenas na execução futura. Provar composição entre declaração, fronteira e contrato com fontes locais; conferir no retro permanências e limites contra o audit. Não prova Origin remoto, produção, economia causal ou segurança de mecanismo substituto de coordenação.

Um único gate final de integração: `scripts/gate-dev --pr <PR de execução>`, no head exato, aguardando o processo terminar, sem espera fixa nem ciclo de consulta. **Não é comando a executar nesta entrega de plano.** A validação desta PR documental é `python3 scripts/lib/commit_check.py --local` e `scripts/structure-check --pr-body <corpo>` sobre esta worktree; são referências de validação, não comandos executados nesta redação. Não se emite `pr.ready`, não se retira o rascunho e não se mergeia nesta etapa.

## Base defects expected

- `KD-3ec4be1f` aberto, dono `engine-lane`, unidade `engine-config`, arquivo `docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml`, conforme o registro lido pela auditoria.
- `KD-024bbecb` e `KD-4db6e693` resolvidos no registro da base; este plano não os reabre nem atribui sua resolução às propostas acima.
- `docs/architecture/ENGINE-OPERATIONS.md` não tem unidade dona: `units.unit_of('docs/architecture/ENGINE-OPERATIONS.md')` → `None`. É fato de atribuição documental registrado no audit, não defeito aberto.

Nenhum desses defeitos foi reproduzido na auditoria ou nesta redação. Registro de base não é prova de execução; nenhum estado aqui foi reconfirmado por gate, trem, bateria ou suite.

## Cheapest useful effort

Action: Vincular a exigência derivada dos consumidores à cobertura contratual recusante de R2, entregue por C1/C3 e integrada em C5.
Cost: 120–180 minutos ativos, quota estimada igual; dinheiro incremental zero. É a maior faixa de esforço escolhida por raiz, incluída no orçamento agregado.
Requirement: Daniel e engine-lane precisam saber se o fluxo de A Torre pode operar com o adaptador escolhido e quais dependências permanecem externas, antes de autorizar execução.
Cheaper rejected: Só documentar a matriz conserva descoberta tardia; ampliar à mão o contrato conserva divergência entre consumidor e prova; anotar o baseline sem recusa conserva classificação facultativa. Manter coordenação foi aceito apenas como remendo com Follow-up, não como solução dessa raiz.

## Execution reconciliation (b715e8be0)

The execution brief authorizes C1/C2/C3/C5 and explicitly skips C4 (#1072).
The current relation measures 18 operations, 45 sites and 19 consumers, rather
than the audit's 38 sites and 14 consumers. Existing operation_demands and adapter
behavioral contracts are reused; GitHub/Origin already implement the relevant
surface, so no redundant adapter declarations are introduced. engine_role already
participates through callers(), including ancestors, and needs no duplicate bind.

C2 also covers push_guard's direct journal construction, as required by the live
brief. C3 updates operation_relations.json's observed lines and crossings after
consumer edits (owner engine-operations); responsibility remains unknown. It also
updates the gate-status fixture to isolate its journal double from forge checks,
while dedicated compatibility tests exercise the real boundary. C2 reconciles
stale consumer expectations in test_forge_events.py. These extra files are needed
to preserve the existing census and test isolation, not new mechanisms.

The D-286 reservation command reported decision-claim lifted and no remote claim.
The global table generator refused preexisting D-258/D-272/D-283 conflicts; only
the D-286 row was rendered with decision_table.row, preserving the older rows.
