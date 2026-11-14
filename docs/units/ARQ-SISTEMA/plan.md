# ARQ-SISTEMA — plan

Entradas: [intake.md](intake.md), [research.md](research.md) e [audit.md](audit.md), sem alteração. Este é o desenho proposto para aprovação de Daniel, não sua execução. Evidências abaixo remetem aos achados e raízes da auditoria; as leituras locais confirmaram os dois combinadores, a seleção de bateria por posse, o extrator de imports e os leitores retirados ainda em AGGREGATES. Não se presume Origin operacionalmente selecionado.

O orçamento se ancora em **R2**: isoladamente, é a maior redução demonstrável de conferência duplicada por mudança de composição — dois algoritmos passam a um. Não há dados para afirmar que seja a maior economia global em minutos; a amostra de 29 commits não separa tempo por raiz. Preservar a reconstrução independente da árvore pelo gate é requisito: compartilhar semântica não autoriza confiar no head recebido. Não prometemos reduzir 2N combinações a N.

## Alternativas

Custos são estimativas de planejamento em minutos de sessão ativa, incluindo provas locais, não medições históricas nem promessa de economia. Quota significa minutos de sessão de agente; tokens e limites do provedor não foram medidos. Sem nova ferramenta, serviço pago ou chamada remota obrigatória. Os intervalos de cada linha incluem apenas aquela alternativa; o orçamento agregado das escolhas está depois das tabelas. Degraus são os da pesquisa: 1 observado, 2 ideal separado, 3 recusa executável.

### R1 — A decomposição por arquivos não expressa exclusividade de operações

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Mapear operações e donos no recorte F1, separando hoje e ideal | remendo | Não; poupa redescobrir quem solicita e quem executa, mas exclusividade ainda exige leitura manual de implementação e mapa | 35–50 min; quota igual | Remover vista documental | Confundir o recorte com censo global | 2 |
| A2 Contrato de operações para todo o engine com prova de dono único | corrige a classe | Sim, se cobrir o universo completo; mudança consulta um contrato em vez de inferir responsabilidade de paths e lane | 120–200 min; quota igual; medir antes o número de operações fora de F1 | Reverter contrato e verificador juntos | Declarar operações sem detectar implementações ocultas | 3 |
| A3 Reorganizar contextos e módulos por contratos operacionais | redesenho | Sim, com migração e recusa; reduz inferência em manifestos e código, além de conferir chamadas no limite | 240–400 min; quota igual; medir consumidores por contexto | Migração reversível por contexto | Movimentação ampla sem economia comprovada | 3 |

### R2 — Composição e verificação da união possuem mecanismos independentes

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Acrescentar teste de paridade entre os dois algoritmos | remendo | Não; detecta divergência, mas cada mudança ainda edita e confere duas implementações | 20–35 min; quota igual | Reverter teste | Casos ausentes dão falsa paridade | 1 |
| A2 Extrair primitiva comum de composição e fazer os dois consumidores usá-la | corrige a classe | Sim; erro, conflito e determinismo têm um mecanismo, sem sincronizar train_git e gate_batch manualmente | 65–100 min; quota igual | Reverter consumidores e extração no mesmo commit | Defeito comum afeta as duas chamadas; preservar oráculos Git independentes nos testes | 3 |
| A3 Protocolo de artefato de lote verificável em fronteira própria | redesenho | Sim; produtores e verificadores usam contrato de artefato, sem reconstruir convenções em cada fluxo | 150–240 min; quota igual | Restaurar protocolo anterior e consumidores | Redefinir prova/cache além da duplicação observada | 3 |

### R3 — Uma mesma porta admite capacidades parciais sem representar sua compatibilidade no limite

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Matriz observada de capacidades por consumidor e adaptador | remendo | Não; evita repetir levantamento de métodos e exceções, mas a compatibilidade ainda é conferida na matriz e no código | 25–40 min; quota igual | Remover matriz | Matriz envelhecer ou virar autorização de troca | 1 |
| A2 Validar requisitos de capacidades na construção de cada fluxo | corrige a classe | Sim; seleção incompatível é recusada antes do uso, sem comparar manualmente superfícies e consumidores | 100–160 min; quota igual | Reverter validação, mantendo adaptadores | Exigir capacidades desnecessárias; baseline externo continua explícito | 3 |
| A3 Separar diário, PR, status e locks em portas tipadas | redesenho | Sim; cada fluxo depende de contrato menor, sem deduzir compatibilidade da fábrica única | 200–320 min; quota igual | Migrar consumidores por porta | Multiplicar interfaces sem terminar migração | 3 |

### R4 — O contrato verificado cobre imports reconhecidos, não todas as ligações de execução

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Listar manualmente as três ligações dinâmicas de F7 | remendo | Não; torna visível a lacuna, mas mantém dois inventários a conferir em cada novo adaptador | 15–25 min; quota igual | Remover lista | Novas ligações escaparem | 1 |
| A2 Representar seleções dinâmicas explicitamente e uni-las ao grafo verificado | corrige a classe | Sim para o mecanismo de seleção dinâmica; um grafo valida requires e alvos, sem conferir lista documental e grafo separadamente | 55–85 min; quota igual | Reverter extensão e declarações juntas | Cadastro omitir ligação; recusar seleção sem declaração e alvo ausente | 3 |
| A3 Encapsular toda seleção em registro tipado de plugins | redesenho | Sim, se não houver fábrica paralela; contratos geram ligações, sem inspeção de importlib por consumidor | 150–240 min; quota igual | Reverter migração da fábrica | Abranger shell e execução indireta sem universo definido | 3 |

### R5 — Posse de código e associação de provas por unidade usam critérios diferentes

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Acrescentar testes aos paths de Origin | remendo | Não; bateria deixa de vazia nesse caso, mas a próxima unidade ainda reconcilia posse e covers | 15–25 min; quota igual | Reverter manifesto | Mudar posse só para influenciar seleção | 1 |
| A2 Derivar provas da interseção entre produção possuída e covers; recusar unidade de produção sem prova | corrige a classe | Sim; covers associa prova e código, posse identifica unidade; não se mantém segunda associação manual de testes | 50–80 min; quota igual | Reverter seleção e regra juntas | Seleção excessiva; fixtures devem distinguir docs, produção e contrato | 3 |
| A3 Contratos de componente como única interface de prova | redesenho | Sim, após migrar cobertura; mudança consulta contrato em vez de mapas de seleção concorrentes | 160–260 min; quota igual | Migrar por unidade com restauração do seletor | Perder provas de integração ao simplificar | 3 |

### R6 — A validade das descrições não está ligada à sobrevivência das relações que descrevem

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Corrigir relações retiradas e separar implementado de selecionado nas vistas existentes | remendo | Não; elimina reconciliação atual de AGGREGATES, UNITS, STRUCTURE e PORTS, mas a próxima retirada ainda exige conferir prosa e código | 25–40 min; quota igual | Reverter docs | Prosa envelhecer novamente | 2 |
| A2 Relações operacionais em fonte verificável, vistas derivadas e recusa de alvo retirado | corrige a classe | Sim para as relações declaradas; mudança edita fato único em vez de repetir leitores em documentos | 90–150 min; quota igual | Reverter gerador e migrar fatos de volta | Tratar presença de arquivo como prova de garantia | 3 |
| A3 Modelo arquitetural executável com cenários e vistas C4/arc42 derivados | redesenho | Sim, com provas semânticas; elimina reconciliação de relações e garantias em vistas independentes | 200–330 min; quota igual | Retomar vistas manuais | Custo de modelo superar uso real | 3 |

### R7 — As visões de prontidão, execução e entrega têm escopos diferentes

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Explicitar no diagnóstico os escopos e o estado desconhecido, sem mudar readyz | remendo | Não; reduz inferência errada e consulta exploratória, mas disponibilidade ainda requer conciliar control, checkout e eventos | 25–40 min; quota igual | Reverter apresentação e testes | Usuário interpretar resumo como prova de executor global | 2 |
| A2 Diagnóstico correlacionado por head/job/lease/prova e transporte | corrige a classe | Sim; uma consulta explica o percurso da mudança em vez de conciliar fontes sem identidade comum | 100–170 min; quota igual | Reverter projeção, preservando fontes | Ausência de dado parecer indisponibilidade comprovada | 3 |
| A3 Contrato de disponibilidade ponta a ponta com identidade de execução | redesenho | Sim; estados derivam de eventos correlacionados, sem equivalência implícita entre saúde e entrega | 200–340 min; quota igual | Migrar leitores antes de remover estados antigos | Mudar semântica operacional sem observação suficiente | 3 |

## Escolha

- R1 → A1: mapa do recorte dá contexto ao conserto demonstrado sem redesenhar 47 unidades. Não satisfaz sozinho a métrica global do intake. Follow-up: unidade proposta ARQ-OPERATIONS, ainda não aberta, para censo completo e contrato recusante A2.
- R2 → A2: âncora do orçamento; remove a segunda implementação, preserva head exato e comparação da árvore. A1 perpetua dupla manutenção; A3 amplia protocolo sem economia medida.
- R3 → A1: a matriz orienta o desenho sem alterar seleção de forja ou fingir que nove métodos equivalem a 24 requisitos. Follow-up: unidade proposta ARQ-FORGE-CAPABILITIES, ainda não aberta, para A2 e tratamento das 13 exceções.
- R4 → A2: fecha a classe de ligações dinâmicas no seletor, reaproveitando o grafo existente. Não tenta inferir toda execução arbitrária nem provar exclusividade semântica de R1; A3 excede o recorte.
- R5 → A2: elimina a associação manual concorrente e exige prova não vazia para produção. A1 resolve só Origin; contratos universais A3 custam migração antes do ganho.
- R6 → A1: remove contradições conhecidas com custo limitado; automatizar toda afirmação agora competiria com R2. Follow-up: unidade proposta ARQ-ARCHITECTURE-VIEWS, ainda não aberta, para fonte de relações e recusa A2.
- R7 → A1: informa limites e incerteza sem modificar serviço ou interpretar snapshot antigo como falha atual. Follow-up: unidade proposta ARQ-EXECUTION-OBSERVABILITY, ainda não aberta, para correlação A2 após medir identidades disponíveis.

Orçamento escolhido: 280–435 minutos ativos, soma das sete faixas; mais 20–35 para integração/retro e duração real do único gate final. Quota estimada igual aos minutos ativos, sem conversão inventada em tokens; dinheiro incremental previsto zero. R1/R3 compartilham um commit documental, mas a soma conservadora não presume desconto. Os follow-ups são propostas identificadas, não unidades ou issues existentes. Entram três correções de classe e quatro medidas limitadas, nenhum redesenho geral. A ordem privilegia R2; se o orçamento estourar, revisar este plano antes de ampliar execução, sem esconder trabalho faltante em um commit.

## Commits

Grafo futuro, **não executado nesta PR documental**: C1 → {C2, C3, C4, C5, C6} → C7. C2 tem prioridade de lançamento. C2–C6 podem ser preparados em paralelo após C1; integração é serial, merge commit de base quando necessário, nunca rebase ou force-push. Todos entregam código e respectivas provas juntos. Caminhos novos abaixo estão explicitamente marcados como propostos, não são evidência da base. Antes de código, registrar a decisão aprovada pelo fluxo de decisões existente; C1 inclui esse registro, cujo número será obtido na execução, sem inventá-lo aqui.

| Commit | Produto e dependência | Arquivos possuídos |
|---|---|---|
| C1 | Hoje/ideal do recorte, operações, matriz R1/R3 e decisão; sem mudar seleção | Novo proposto `docs/architecture/ENGINE-OPERATIONS.md`; registro de decisão a reservar e sua geração de `docs/domain/DECISIONS.md` |
| C2 | R2: uma primitiva, dois chamadores e comparação independente; depende C1 | Novo proposto `scripts/lib/merge_composition.py`; `scripts/lib/train_git.py`, `scripts/lib/gate_batch.py`; `scripts/tests/test_gate_batch.py`; novo proposto `scripts/tests/train/test_merge_composition.py`; covers de train e gate-batch correspondentes |
| C3 | R4: relações dinâmicas no grafo, com recusa; depende C1 | `scripts/lib/unit_map.py`, `scripts/lib/unit_check.py`, `scripts/lib/forge_events.py`; `scripts/tests/test_unit_map.py`, `scripts/tests/test_unit_check.py`; covers de units; novo proposto `scripts/lib/dynamic_relations.json` |
| C4 | R5: associação por covers e recusa de produção sem prova; depende C1 | `scripts/lib/unit_battery.py`, `scripts/tests/test_unit_battery.py`; covers de battery |
| C5 | R6: corrigir leitores retirados e terminologia; depende C1 | `docs/architecture/AGGREGATES.md`, `docs/architecture/UNITS.md`, `docs/architecture/PORTS.md`, `docs/process/STRUCTURE.md` |
| C6 | R7: distinguir estado local, remoto e prova no diagnóstico, inclusive desconhecido; depende C1 | `scripts/lib/service_status.py`, `scripts/tests/test_service_status.py`; covers de service; `docs/operations/services.md` |
| C7 | Recontagem do recorte, comparação com baseline e retro; depende C2–C6 | Novo proposto `docs/units/ARQ-SISTEMA/retro.md` |

“Covers correspondentes” significa o manifesto existente da suite nomeada em `scripts/tests/covers/`, conferido antes da edição; não criar associação redundante. Nenhum arquivo é possuído por dois commits paralelos. Se forem necessários ajustes cruzados (por exemplo requires da primitiva nova), serializar C3 após C2 e registrar no plano antes de editar. Não mover arquivos entre unidades por conveniência de seleção.

## Premises

Premises: none

Não adotamos premissa não confirmada para selecionar forja, trocar fonte da verdade ou atribuir duração causal às raízes. Custos são estimativas com raio restrito ao orçamento de execução. Fonte da verdade, produção e dinheiro são limites do escopo, não hipóteses: qualquer proposta que os altere é CRITICAL, exige revisão do escopo por Daniel e não está autorizada por este plano. As descrições identificam revisão e recorte; o snapshot F10 não é uma premissa sobre disponibilidade atual.

## Tests

- C1: conferir cada operação da vista com chamadores/implementações na revisão identificada; separar observado, ideal e desconhecido. Conferir matriz por consumidor, não exigir todos os métodos de todos os adaptadores.
- C2: `scripts/run test train` e `scripts/run test gate-batch`. Casos: lote limpo, ordem, conflito com arquivos, erro sem arquivos, determinismo entre chamadas e head fornecido de árvore errada recusado. Oráculo em repositório Git temporário, não expectativa calculada pela mesma primitiva.
- C3: `scripts/run test units` e `scripts/run test forge-events`. Fixtures aceitam import/seleção legítimos, recusam requires ausente, alvo removido e seleção dinâmica não declarada. Provar que GitHub/control/Origin entram no grafo; não confundir grafo verde com compatibilidade R3.
- C4: `scripts/run test battery` e teste direto `python3 scripts/tests/test_unit_battery.py`. Produção Origin obtém prova via covers; fixture de produção sem associação é recusada; docs não ganham prova artificial; contrato e consumidor continuam cobertos. Sem testes live obrigatórios.
- C5: conferir leitores retirados de F9 contra árvore, consistência entre quatro documentos e diferenças entre adaptador implementado e selecionado; `scripts/structure-check` como check direcionado, registrando exceções da base.
- C6: `scripts/run test service`, usando fontes falsas: remoto ausente, heartbeat antigo, merge recente e runner local ausente permanecem estados distintos; nenhuma chamada inicia/para serviço ou muda readyz.
- C7: recontar algoritmos de composição (alvo um), ligações dinâmicas ausentes no recorte (alvo zero), produção sem prova no universo declarado (alvo zero). Repetir a amostra histórica F2 com a mesma regra e registrar arquivos/unidades, sem atribuir causalidade a mediana. Medir minutos de uma alteração de composição e uma inclusão de adaptador em fixtures antes/depois; informar observação, sem extrapolar para todo commit.

Um único gate de integração no fim da execução: `scripts/gate-dev --pr <PR de execução>`, no head exato; aguardar saída do processo, sem polling ou espera fixa. Não é comando a executar nesta entrega de plano. A validação desta PR documental é `python3 scripts/lib/commit_check.py --local` e `scripts/structure-check --pr-body <corpo atualizado>` sobre esta worktree. Não emitir pr.ready, não retirar rascunho nem mergear nesta etapa.

## Base defects expected

- KD-3ec4be1f permanece `open`, dono `engine-lane`, unidade `engine-config`, no registro `docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml`, reconferido nesta sessão: evento inválido pode causar `config.StoreError`. Não reproduzido aqui, não declarar sanado por check documental.
- F4 e F6–F9 continuam sendo entradas desta árvore; donos `engine-train`, `engine-gate-verdict`, `engine-events`, `engine-forge-github`, `engine-forge-origin`, `engine-units`, `engine-structure`, todos `engine-lane` conforme auditoria. O plano trata R2/R4/R5 e limita R1/R3/R6; não camuflar dívida restante como falha nova.
- F10 é snapshot histórico, não defeito operacional atual reconfirmado; dono `engine-service` / `engine-lane`. Nenhum reparo de serviço integra este plano.
- Avisos e recusas levantadas pelo regime D-260 citados em F9 devem ser comparados com a saída real do check desta entrega; dono da base `engine-lane`, política Daniel. Saída zero sob esse regime não comprova recusa ativa. Se o pre-push recusar defeito de base, parar e relatar, sem bypass.

## Cheapest useful effort

Action: Unificar a semântica de composição (C2/R2) com provas independentes dos dois consumidores.
Cost: 65–100 minutos ativos de sessão/quota; sem gasto adicional previsto. É a maior faixa de esforço escolhida; integração/gate será medida separadamente, sem estimar tokens não observados.
Requirement: Daniel e engine-lane precisam alterar composição sem manter dois algoritmos e sem perder a prova de head/árvore.
Cheaper rejected: Só documentar preserva dupla manutenção; testar paridade detecta divergência mas conserva duas fontes; aceitar o head do trem sem reconstruir a árvore poupa computação às custas da prova existente. O protocolo novo de artefato custa mais e não é necessário para este ganho.
