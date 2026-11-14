# ARQ-OPERATIONS — plan

Entradas: [audit.md](audit.md) e [research.md](research.md); as contagens são as medidas pela auditoria nesta árvore.
Este é o plano proposto para aprovação de Daniel, não sua execução. As quatro raízes permanecem as da auditoria.
O objeto é a operação no recorte da forja; posse de arquivo, implementação e consumo continuam relações distintas (F1–F3).
As referências Backstage, OPA e ArchUnit informam catálogo, política e confronto com código; não determinam ferramenta ou schema (research, Estado da arte).

## Alternativas

Custos são estimativas de planejamento em minutos de sessão ativa, incluindo provas locais, não medições históricas nem promessa de economia.
Nenhuma ferramenta ou serviço pago novo é necessário. As faixas incluem a integração pertinente a cada raiz; não presumem desconto por trabalho compartilhado.
Os degraus são os da pesquisa: 1 vocabulário/alcance; 2 relações operação ↔ dono ↔ consumidor expostas; 3 censo completo e contrato recusante.
Recusas no recorte declarado não equivalem ao degrau 3 global. As contagens são as da auditoria, que fixa a interpretação de universo em F1–F8.

### R1 A operação não tem representação declarada e só existe como nome no ponto de chamada

Classe: arquitetura/desenho; evidência: auditoria R1/F1/F7. O mapa não é declaração governante nem denominador global.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Completar e atualizar o mapa documental existente | remendo | Não; o nome continua governado pelo ponto de chamada, sem relação verificada | 25–40 min | Reverter atualização do mapa | A lista parecer completa e envelhecer sem detecção | 1 |
| A2 Declarar operações observadas em relação legível por verificador, com dono, consumidores e desconhecidos | corrige a classe | Sim no recorte confrontado com chamadas; a operação passa a ter representação própria | 70–110 min | Reverter declaração e leitor juntos, preservando o levantamento documental | Declarar operação sem detectar implementação oculta; busca textual não prova equivalência semântica | 2 |
| A3 Tornar a operação a unidade de fronteira do modelo, declarada, contada e confrontada em todo o engine | redesenho | Condicional; exige descobrir e demonstrar o universo antes de afirmar cobertura | 240–400 min; faixa inicial sujeita ao levantamento | Migrar por fronteira e restaurar relações anteriores em cada trecho | Denominador global inexistente impede fechar custo e alvo; formalizar lacunas como completude | 3 |

A2 parte dos nomes observados em `_operation`, sem promover auxiliares ou `change` ao mesmo denominador (F1/F6).
O formato da relação será pesado na execução com os leitores existentes; esta escolha não fixa schema nem nova divisão de unidades.

### R2 A fronteira aceita superfícies sem prova de compatibilidade por operação

Classe: mecanismo faltando; evidência: auditoria R2/F5/F6. Presença de método e prova de comportamento não são equivalentes.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Consolidar no contrato a cobertura das operações já implementadas pelos dois adaptadores | remendo | Não; o subconjunto comum já coberto deixa 13 operações sem prova de contrato | 25–40 min | Reverter os casos acrescentados | Contrato comum continuar sugerindo compatibilidade maior que a exercitada | 1 |
| A2 Exigir prova de compatibilidade por operação requerida na fronteira, com recusa antes do uso | corrige a classe | Sim no recorte declarado; ausência ou prova insuficiente deixa de ser descoberta na chamada | 100–160 min | Reverter validação e integração da fronteira juntas | Confundir método presente com prova; exigir operação não consumida ou bloquear fluxo legítimo | 2 |
| A3 Condicionar a seleção do adaptador à matriz de compatibilidade exigida pelos consumidores | redesenho | Sim se demandas e provas cobrirem a seleção inteira; não está demonstrado fora do recorte | 200–320 min | Restaurar seleção anterior após reverter consumidores migrados | Matriz incompleta autorizar seleção inadequada; denominador de consumidores ainda não fechado globalmente | 3 |

A2 confronta demanda declarada e prova correspondente, sem exigir que todo adaptador implemente toda operação (F2/F6).
A passagem direta `change` permanece explicitamente adjacente, com tratamento de falha examinado sem adulterar a contagem (F5/F6).

### R3 Nenhuma regra liga a operação ao responsável; a posse verificada é a de arquivo

Classe: regra faltando; evidência: auditoria R3/F2/F3/F7. Multiplicidade de implementadores não prova duplicação indevida.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Registrar responsável por operação somente no documento | remendo | Não; nenhuma regra impede ausência ou atribuições concorrentes | 20–35 min | Reverter coluna documental | Confundir dono do método ou lane comum com responsável pelo comportamento | 1 |
| A2 Verificar responsável único por operação declarada, recusando ausência e conflito | corrige a classe | Sim no recorte declarado; a relação deixa de depender da inferência por caminho | 55–85 min | Reverter regra e atribuições juntas | Nomear responsável sem atribuição aceita; operação oculta continuar fora da regra | 2 |
| A3 Reorganizar a atribuição para a operação ser a unidade de coordenação | redesenho | Condicional à migração de responsabilidades e relações de consumo | 180–300 min; inclui migração de atribuições | Restaurar coordenação anterior por relação migrada | Transferir responsabilidade sem transferir capacidade de atuação; migração amplia coordenação | 3 |

A2 não muda posse física nem exige exclusividade de implementação: verifica quem responde pela operação (R3).
A atribuição será submetida ao fluxo de decisão, sem tomar a lane efetiva como aceite automático de cada responsabilidade (F8).

### R4 A operação e sua configuração não têm fronteira própria

Classe: arquitetura/desenho; evidência: auditoria R4/F4. O histórico mede introdução, não duração humana de toda mudança.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Documentar quais chaves pertencem a qual operação | remendo | Não; a associação continua externa à fronteira e sem recusa | 25–40 min | Reverter tabela de associação | Atribuir chave compartilhada arbitrariamente ou deixar a tabela divergir | 1 |
| A2 Delimitar configuração por operação declarada e recusar chave órfã no recorte | corrige a classe | Sim no recorte; associação e leitura passam a ser confrontadas, com compartilhamento explícito | 80–130 min | Reverter delimitação e verificação juntas, preservando valores do registro | Confundir chave da seleção da forja com chave operacional; leitura indireta escapar ao confronto | 2 |
| A3 Separar a fronteira de configuração da forja por operação | redesenho | Condicional à migração dos leitores e das chaves compartilhadas | 200–340 min; inclui migração dos leitores | Restaurar leitores anteriores antes de retirar a fronteira nova | Multiplicar configuração e geração sem isolamento demonstrado; custo extrapola as introduções medidas | 3 |

As chaves observadas são entrada para classificação, não prova de que cada chave pertença exclusivamente a uma operação (F4).
A2 expõe compartilhadas e desconhecidas antes de aplicar recusa; não inventa pertencimento para fechar a tabela.

## Escolha

- R1 → A2: resolve a ausência de representação no recorte, com custo limitado e reversão conjunta de declaração/leitor; A1 mantém convenção nominal e A3 exige denominador inexistente. Degrau 2, com risco de implementação oculta declarado.
- R2 → A2: remove descoberta tardia para demandas comprovadas, com recusa anterior ao uso e reversão na fronteira; A1 deixa 13 sem prova e A3 amplia seleção sem cobertura global. Degrau 2; prova comportamental continua necessária.
- R3 → A2: institui a regra ausente sem migrar coordenação e caminhos; custa menos e se desfaz com as atribuições. A1 não recusa conflito; A3 exige migração não justificada pelo alcance textual. Degrau 2, sem presumir aceite de responsável.
- R4 → A2: associa configuração à fronteira declarada e confronta órfãs; desfaz-se sem trocar valores. A1 mantém reconciliação manual e A3 amplia migração sem custo causal medido. Degrau 2; compartilhamento não será forçado a dono exclusivo.

Orçamento escolhido: 305–485 minutos de sessão ativa, soma das quatro faixas; estimativa de planejamento, não medição da auditoria.
A execução deve medir duração real e rever o plano se o recorte não permitir as provas, antes de ampliar alcance.
A escolha não resolve censo global, exclusividade semântica de implementações ocultas ou compatibilidade de consumidores não observados.
Não transforma alcance textual em grafo de execução nem demonstra disponibilidade remota; esses limites são os de F3/F8 e da pesquisa.

## Commits

Grafo futuro, **não executado nesta PR documental**: C1 → C2 → {C3, C4} → C5.
C1 e C2 são seriais; C3 e C4 podem ser preparados em paralelo; C5 integra serialmente depois deles.
Cada commit de implementação entrega código e prova juntos; C1 entrega o registro da decisão e sua conferência, antes do código.
Caminhos novos abaixo são **propostos**, não evidência da base; nomes e encaixe devem ser confirmados antes de implementar.

| Commit | Produto e dependência | Arquivos possuídos |
|---|---|---|
| C1 | Registrar decisão aprovada pelo fluxo existente, escopo e limites; sem implementação | Novo registro proposto em `docs/domain/decisions/`, com número obtido na execução, e linha correspondente em `docs/domain/DECISIONS.md`; nenhum número reservado aqui |
| C2 | R1: relação observada consultável e confronto com chamadas; depende C1 | Novos propostos `scripts/lib/operation_relations.json`, `scripts/lib/operation_relations.py`, `scripts/tests/test_operation_relations.py`; `docs/architecture/ENGINE-OPERATIONS.md` |
| C3 | R2: compatibilidade por demanda e recusa antes do uso; depende C2 | `scripts/lib/forge_events.py`, `scripts/tests/forge_events/test_forge_contract.py`, `scripts/tests/test_forge_events.py`, `docs/architecture/PORTS.md` |
| C4 | R4: delimitação de configuração e confronto de órfãs; depende C2 | Novos propostos `scripts/lib/operation_config.py`, `scripts/lib/operation_config_relations.json`, `scripts/tests/test_operation_config.py`; `scripts/tests/test_config_registry_readers.py` |
| C5 | R3 e integração: responsável único recusante, ligação das verificações e provas cruzadas; depende C3/C4 | `scripts/lib/unit_check.py`, `scripts/tests/test_unit_check.py`, `scripts/tests/covers/forge-events.json`, `scripts/tests/covers/config-readers.json`; novo proposto `scripts/tests/test_operation_integration.py` |

C2 expõe a atribuição observada e o desconhecido; C5 aplica a regra aprovada, sem inferir exclusividade pela implementação.
C4 deve incluir código de delimitação consumível e sua prova, não apenas uma tabela sem leitor; C5 liga sua recusa à verificação conjunta.
Nenhum arquivo pertence aos dois commits paralelos. Ajuste necessário na relação de C2 ou na porta de C3 será serializado em C5.
Os arquivos já possuídos por commits anteriores só podem ser revisitados após suas dependências; não haverá edição concorrente deles.
Os manifestos de covers serão conferidos na execução antes da associação de provas; não mudar posse para obter seleção conveniente.

## Premises

Premises: none

A escolha não depende de seleção remota em `github`, serviço disponível ou aceite tácito da `engine-lane`.
A decisão aprovada e a atribuição explícita são condições anteriores à implementação, não fatos presumidos; ausência delas exige rever este plano.
Escopo, dinheiro, produção e fonte da verdade ficam limitados ao recorte local e ao fluxo existente; mudança nesses limites é CRITICAL e requer decisão de Daniel.
Não há premissa externa usada para prometer cobertura global ou economia humana (auditoria F8; research, Escada de ambição).

## Tests

Alvos futuros por commit; nenhuma execução abaixo é declarada nesta PR documental.

- C1: conferir registro aprovado e linha do índice contra o fluxo existente; `scripts/tests/test_structure_intake.py` e `scripts/tests/test_structure.py` são alvos reais para a disciplina documental.
- C2: novo proposto `scripts/tests/test_operation_relations.py`: confronto com nomes literais, operação não declarada, consumidor desconhecido e distinção entre implementação e responsabilidade; mapa deve preservar limites de F1/F3/F7.
- C3: reais `scripts/tests/forge_events/test_forge_contract.py` e `scripts/tests/test_forge_events.py`: demanda atendida, ausente e sem prova; recusa antes de efeito; adaptador parcial válido para consumidor compatível; passagem direta examinada separadamente (F5/F6).
- C4: novo proposto `scripts/tests/test_operation_config.py` e real `scripts/tests/test_config_registry_readers.py`: chave órfã recusada, compartilhada explícita aceita, seleção da forja distinguida de configuração operacional; sem escrever dados externos.
- C5: real `scripts/tests/test_unit_check.py` e novo proposto `scripts/tests/test_operation_integration.py`: responsável ausente ou concorrente recusado, dono único aceito, integração das recusas de compatibilidade/configuração e preservação de posse de caminho.

Um único gate final na execução: `scripts/gate-dev --pr <PR de execução>`, no head exato, aguardando a saída do processo.
Esse gate **não é executado nesta PR documental**. Provas futuras devem usar fixtures locais e oráculos independentes da declaração sob teste.

## Base defects expected

Esperados para confronto com a saída na execução, não reparados aqui; fonte: auditoria, Base defects expected.
O KD aberto é `docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml`, dono `engine-lane`, unidade `engine-config`; não foi reproduzido aqui.
Os registros `scripts-tests-premises-test-sh-4db6e693.yml` e `scripts-tests-generate-test-sh-024bbecb.yml`, no mesmo diretório, estão `resolved` e não contam como abertos.
A dívida documental inclui `docs/architecture/PORTS.md:12` e a docstring em `scripts/lib/forge_events.py:7-17` desatualizadas (F7).
Inclui `docs/architecture/ENGINE-OPERATIONS.md` sem dono e sem referência no código; não é KD registrado (F7).
A atribuição operacional dessa dívida é `engine-lane`, pela porta em `engine-events`; não equivale a posse declarada dos documentos (auditoria, Base defects expected).
A execução confrontará essa dívida com C2/C3/C5; este plano não declara correção nem transforma defeito esperado em falha nova.

## Cheapest useful effort

Action: Exigir prova de compatibilidade por operação requerida e recusar incompatibilidade antes do uso na fronteira (R2/A2, C3), maior faixa individual escolhida.
Cost: 305–485 minutos de sessão ativa, soma de R1/A2 70–110, R2/A2 100–160, R3/A2 55–85 e R4/A2 80–130; estimativa de planejamento incluindo provas locais, sem serviço pago novo.
Requirement: Daniel e engine-lane precisam consultar responsabilidade operacional explícita e alterar o recorte com prova de compatibilidade e configuração delimitada, sem inferir essas garantias da posse dos arquivos.
Cheaper rejected: Só atualizar o mapa não cria regra; registrar dono só em prosa não recusa ausência ou conflito; cobrir só operações comuns deixa 13 sem prova; listar chaves sem confronto mantém órfãs possíveis. Censo completo não é atalho mais barato: sem denominador custa mais e não tem alvo demonstrado (F1/F6/F7; research).
