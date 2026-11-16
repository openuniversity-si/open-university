# PADRAO-DEV — solução

Uma escolha entre alternativas, cada uma com custo, alcance e requisitos (método §2, passo 4). As fases vêm depois da
escolha e são unidades de progresso dentro dela. Base: a [avaliação](avaliacao.md), a [pesquisa](pesquisa.md) e a
[análise](analise.md) (cadeia verificada 0 %; inventário de pelo menos 406 requisitos em sete fontes; escape 10,9 %;
causas C0 a C5).

**Revisão 2** (correção de Daniel, 15/11 20:42 e 20:44 BRT). A primeira versão escolheu "o padrão como sistema
verificável" centrado na taxa de escape, com duas fases de teste, requisitos na última e arquitetura reduzida a "todo
arquivo tem unidade". Ela entra abaixo como alternativa descartada (B2), e as fases foram refeitas.

## Alternativas

| | Alternativa | Custo | Alcance | Requisitos | Risco | Reversível |
|---|---|---|---|---|---|---|
| B1 | **Padrão em prosa**, organizado pelas áreas do SWEBOK, no brief e no AGENTS.md | baixo | nenhum sistema passa a existir | nenhum | alto: prosa de contexto custa mais de 20 % e não muda o sucesso (Gloaguen 2026; Hill, ESEM 2026) | sim |
| B2 | **A solução da revisão 1:** catálogo de regras com checagem, seleção derivada, adequação medida, centrado no escape | médio-alto | padrão, construção e testes; requisitos e arquitetura tardios e parciais; nenhum modelo que ligue as partes | `strace`, `coverage.py`, `ruff`/`pyright` | médio | sim |
| B3 | **Comprar uma ferramenta de ALM** (Polarion, Jama, Codebeamer) mais Backstage e Structurizr como serviços | alto e recorrente (dinheiro: decisão do dono) | requisitos, testes e rastreio; arquitetura e padrão por integração | contas, credenciais, integração com o GitHub por MCP ou API | alto: o modelo sai do repositório, que é a fonte da verdade e o caminho da fila; os agentes escreveriam por uma segunda via | caro |
| B4 | **Adotar uma ferramenta "como código"** (Sphinx-Needs, OpenFastTrace, StrictDoc) como motor do modelo | médio | requisitos → testes bem; arquitetura, decisões, unidades, registro e padrão só por adaptadores | Sphinx/RST ou Java no toolchain; rastreio por marcas no código | médio: uma segunda forma de dado ao lado dos nossos contratos JSON Schema | sim |
| B5 | **Um modelo de engenharia próprio no repositório.** Um metamodelo como contrato (tipos de objeto, estados, tipos de ligação, regras de ligação e de cobertura); um arquivo por objeto, na fonte autoritativa de cada sistema; um comando que monta o grafo e calcula ligações suspeitas, estados derivados, cobertura, a medida e a conformidade de cada sistema; uma etapa do gate que recusa a mudança que quebra o modelo | alto: 8 fases, cerca de 50–70 PRs pequenas | os 15 sistemas e a cadeia de ponta a ponta | nada fora do que já temos (Python, JSON Schema, o gate, a fila); `strace`, `coverage.py`, `ruff` e `pyright` fixados no toolchain quando as fases de construção e de verificação chegarem | médio: uma regra com falso positivo trava o fluxo, mitigado pelo caminho aviso → medida → bloqueio | sim, por tipo e por regra |

## Escolha
**B5, o modelo de engenharia próprio no repositório.** É a única alternativa em que todos os sistemas passam a existir
com os sete atributos e se ligam num só modelo, e é a forma que a pesquisa encontrou em quem faz isso bem: um grafo
tipado de objetos com ids estáveis, uma fonte autoritativa por objeto, ligações tipadas e versionadas, estados
derivados, conformidade calculada (OSLC, ASPICE, DO-178C, Polarion, Codebeamer, Backstage). O git já é o servidor do
modelo: cada commit de `main` é uma versão dele, e cada PR é um delta que a fila julga. E a B5 aproveita o que existe
em vez de recomeçar: as decisões com prova, as unidades com dependências conferidas, o registro com leitores
conferidos, as premissas com raio, as capacidades com estado, os eventos com contrato e o gate por plano.

- **De B4 fica o desenho, não a ferramenta:** o grafo de "needs" do Sphinx-Needs, os ids com revisão do OpenFastTrace,
  um arquivo por item como no Doorstop.
- **De B3 fica o mecanismo:** a ligação suspeita, as guardas de transição, a aprovação só com teste que verifica, e um
  índice consultável para os agentes (o que o MCP da Jama e do Backstage oferece), aqui como um comando local.
- **De B2 fica o que era certo, como parte dos sistemas:** o catálogo de regras é o sistema Padrão; a seleção derivada
  e a adequação são do sistema Verificação; o rascunho do comando que mediu a seleção (`padrao-metrics selection`) volta
  na fase de Verificação.

## O modelo único
Um contrato, `contracts/model/metamodel.v1.json`, declara os tipos de objeto, os estados de cada tipo, os tipos de
ligação (o vocabulário do OSLC sempre que existe), quais ligações valem entre quais tipos e o que cada tipo precisa
ter para estar coberto. Cada objeto vive na fonte autoritativa do seu sistema, um arquivo por objeto, com `id`
estável, `type`, `state`, `owner` e as suas ligações. A ligação é guardada no objeto de baixo da cadeia (quem conhece a
ligação é quem a declara) e grava a impressão digital do alvo.

```
INT  intenção         <- NEED  necessidade      --refines-->      INT
NEED necessidade      <- REQ   requisito        --derives-from--> NEED
REQ  requisito        <- ARC   elemento de arq. --satisfies-->    REQ        (capacidade, componente, contrato/porta)
ARC  elemento         <- UNIT  unidade          --realizes-->     ARC
UNIT unidade          -- depends-on / provides / consumes -->     UNIT | CON | CFG
D    decisão          -- affects --> REQ|ARC|UNIT|CFG ; -- proved-by --> TEST ; -- supersedes --> D
CHG  mudança (PR)     -- implements --> REQ|UNIT ; -- tracks --> item de trabalho
TEST teste            -- verifies --> REQ|D|UNIT          VERD  veredicto  -- evidences --> TEST @ sha
VAL  validação        -- validates --> NEED|REQ ; -- measured-by --> MEAS
P    premissa/risco   <- D|REQ --assumes--> P              INC  incidente  -- violates --> REQ|VAL ; -- fixed-by --> CHG
STD  regra do padrão  -- applies-to --> tipo|sistema       TAIL isenção    -- exempts --> STD ; -- authorized-by --> D
PROP proposta         -- changes --> STD ; -- decided-by --> D              VER   versão do padrão -- contains --> STD
```

O que o torna verificável, e quem verifica:

1. **Integridade referencial** (o gate): toda ligação aponta para um id que existe e é de um tipo permitido.
2. **Ligação suspeita** (o gate): se a impressão digital atual do alvo difere da gravada, a ligação está suspeita; o
   impacto de uma PR é o fecho, para baixo, do que ela altera. Uma ligação suspeita num objeto aprovado bloqueia a
   transição de estado até ser rejulgada.
3. **Cobertura por tipo** (o gate): NEED precisa de REQ e VAL; REQ precisa de ARC e TEST; ARC precisa de UNIT; UNIT
   precisa de TEST e de pelo menos um ARC (a regra inversa da DO-178C: unidade sem requisito é código a mais); D
   precisa de prova.
4. **Estados derivados** (o comando): implementado = existe uma mudança mergeada que implementa; verificado = todos os
   testes que verificam estão verdes no sha de `main`; validado = a validação está atendida. Ninguém edita esses
   estados.
5. **Consistência** (julgamento registrado): que a ligação está semanticamente certa só se julga em ligações novas ou
   suspeitas, por uma sessão validadora, e o julgamento fica como evento com a impressão digital que confirmou (ASPICE;
   LLMs validam ligações bem).
6. **Conformidade calculada** (o comando, a cada merge): por sistema, a fração dos seus objetos que cumpre as regras do
   padrão que se aplicam a ele, menos as isenções vigentes, na escala N (até 15 %), P (até 50 %), L (até 85 %), F
   (acima de 85 %).

O comando `scripts/model` faz `check` (as verificações 1 a 3, a etapa do gate, só nos objetos que o diff toca para
caber nos 60 s), `show <id>` (o objeto, as ligações para cima e para baixo e o estado, o índice que um agente consulta
em vez de ler documentos) e `measure` (a métrica principal, a medida e a conformidade de cada sistema, como artefato
gerado).

## Os sistemas
Quinze sistemas: os 30 processos da 15288 e da 12207 agrupados pelo objeto que gerem (a [pesquisa](pesquisa.md), §10),
com padrão e gestão do padrão separados. Todo sistema tem dono (o domínio Administração da AGENTS.md, salvo onde a
tabela diz outro), registro como dado (um arquivo por objeto, o agregado gerado), ligações com os vizinhos (o modelo
acima), uma medida própria e a conformidade calculada (ver o modelo, item 6).

| Sistema | Processos (12207/15288) e áreas (SWEBOK) | Objeto gerido | Estados | Onde vive | Medida própria | Linha de base |
|---|---|---|---|---|---|---|
| Intenção | análise do negócio; necessidades dos interessados | INT, NEED | proposta → validada pelo dono → ativa → substituída | a [semente](../../SEMENTE.md) e as instruções de Daniel, como objetos | NEEDs com REQ e VAL | intenção e metas só em prosa |
| Requisitos | definição de requisitos; SWEBOK 1 | REQ: produto, operação, qualidade, restrição, interface; enunciado EARS | rascunho → aprovado → implementado* → verificado* → substituído/obsoleto (*derivados) | novo, um arquivo por requisito; INV, G, SLO e orçamentos importados | REQs com cadeia verificada; ligações suspeitas | 0 %; sete fontes, cinco vocabulários |
| Arquitetura | definição de arquitetura e de projeto; SWEBOK 2, 3 | ARC: sistema, capacidade, componente, contrato e porta; visões geradas | proposto → ativo → obsoleto → retirado | `docs/capabilities`, `contracts/`, `docs/architecture`, a arquitetura de referência, como objetos | conformidade de reflexão: convergências ÷ (convergências + divergências + ausências) | 0 de 33 ADRs com confirmação; não medida |
| Decisões | gestão de decisões | D (as ADRs entram como D) | proposta → aceita (imutável) → obsoleta / substituída por | `docs/domain/decisions/` e `docs/adr/` | decisões aceitas com prova verde; substituições marcadas | 79 de 81 provas existem; ADR-24 contrariada sem marca |
| Trabalho | portfólio, planejamento, avaliação e controle; SWEBOK 9 | item de trabalho (programa, projeto, unidade da fila, plano de commits) | na fila → tomado → em curso → entregue | `docs/programs/`, a fila, o plano de commits | vazão, WIP, tempo por PR, idade da fila | `flow-metrics`; sem ligação a REQ |
| Construção e entrega | implementação, integração, transição; SWEBOK 4 | UNIT, código, CHG (PR), release | rascunho → pronta → na fila → mergeada → implantada → (revertida) | `units/`, as PRs e os eventos | mergeadas na 1ª rodada; código sem unidade; achados de construção sem piora | 368 arquivos sem unidade; sem lint/tipos de Python |
| Verificação | verificação; SWEBOK 5 | TEST com nível (unidade, integração, sistema) e nível de integridade; VERD | proposto → ativo → em quarentena → retirado; veredicto por sha | `scripts/tests/`, os veredictos do gate | REQs com teste; completude da seleção; adequação (cobertura do diff, mutação); instabilidade | 207 de 214 testes com seleção incompleta; adequação não medida |
| Validação | validação | VAL: necessidade → medida, limiar, janela; o teste de validação final | definida → medindo → atendida / não atendida → revista | novo | NEEDs com VAL atendida; distância à escada | nenhuma VAL; um canário de deploy |
| Configuração | configuração, informação, descarte; SWEBOK 8 | CFG: chave do registro, contrato, pin do toolchain; a baseline (commit de `main`) | proposta → ativa → obsoleta → retirada | `config/registry/`, `contracts/`, o toolchain | deriva (gerado ≠ fonte); itens sem dono | leitores conferidos; driver de merge só local |
| Operação | operação, manutenção, infraestrutura; SWEBOK 6, 7 | serviço, ambiente, INC | aberto → mitigado → resolvido → revisto | `docs/process/incidents`, os serviços | MTTR; incidentes com causa ligada a REQ/VAL | 2 incidentes, 3 postmortems, sem ligação |
| Medição | medição, análise de sistema; SWEBOK 15 | MEAS (15939: necessidade, função, indicador, critério de decisão) | proposta → ativa → retirada | novo; `flow-metrics`, `medir`, `slo` como fontes | medidas com necessidade e consumidor | medidas sem metadado |
| Conformidade | gestão e garantia da qualidade; SWEBOK 12; segurança como checagens | a avaliação por sistema e por regra num sha | calculada a cada merge, imutável | gerada | nível N/P/L/F por sistema e tendência | não existe |
| Padrão | modelo de ciclo de vida; SWEBOK 10, 11 | STD: regra com id, fundamento, `applies-to`, checagem, testes da checagem, modo | rascunho → em aviso (com prazo) → em bloqueio → substituída | novo, um arquivo por regra; o METODO, o v8, D-069 e as 49 recusas importados | regras com checagem; regras em aviso fora do prazo | 1 de 49 recusas registradas; dois modos de relatório sem prazo |
| Gestão do padrão | gestão do modelo de ciclo de vida (estabelecer, avaliar, melhorar); CMMI OPD/OPF | PROP (proposta de mudança), VER (versão), TAIL (isenção) | proposta: aberta → em aviso → decidida → aplicada / rejeitada | novo; as lições, as contestações de regra e `docs/padrao/v*` importados | propostas decididas no prazo; isenções vigentes; conformidade do próprio padrão | 0 de 32 lições propostas; 7 contestações sem ciclo |
| Conhecimento | gestão do conhecimento e de riscos; SWEBOK 14 | P (premissa e risco), lição, fricção, instrução de agente | premissa: inferida → a validar → confirmada / refutada; fricção: aberta → unidade → fechada | `docs/process/premises`, `lessons`, fricções, `repeats` | premissas de raio alto sem confirmação; ações manuais repetidas | 58 premissas, 32 vencidas pelo `rule check` |

Ficam fora, com a razão na pesquisa: aquisição e fornecimento, segurança como sistema próprio, as áreas de
fundamentos. A lista é ela mesma um objeto do sistema Gestão do padrão: mudá-la é uma proposta.

**Regras para toda mudança**, que o padrão impõe desde a primeira fase:
- nada que se deriva é escrito à mão;
- uma lista que só cresce é um diretório de arquivos, um por entrada, com o agregado gerado;
- toda regra nova chega com a sua checagem e os testes dela, em aviso com prazo, e passa a bloqueio quando a medida de
  falsos positivos permite;
- uma decisão aceita não se edita: substitui-se.

## Fases
Cada fase tem auditoria técnica, planejamento, execução e verificação (método §2), num arquivo `phases/F<n>.md` aberto
quando a fase começa, e fecha com o painel inteiro medido e a pergunta se o objetivo melhorou ou só o número (D-133).
A ordem põe primeiro o que configura os outros (o modelo e o padrão), depois as duas pontas que mais faltam
(requisitos e arquitetura), e só então construção, verificação e validação.

| Fase | Meta | O que muda | Critério de parada da fase | Tamanho |
|---|---|---|---|---|
| F1 O modelo, o Padrão e a gestão do padrão | o metamodelo existe e é checado no gate; o padrão é um sistema | `contracts/model/metamodel.v1.json`; `scripts/model check/show/measure`; a etapa do gate em aviso; o sistema Padrão (um arquivo por regra, semeado com as 49 recusas, os 16 princípios D-069, as etapas do gate e o METODO) e a Gestão do padrão (propostas com ciclo, versão v9 em `docs/padrao/v9/`, isenções); os dois modos de relatório ganham prazo; a decisão do programa como D-NNN com a prova | `scripts/model measure` calcula a linha de base (0 %) e a conformidade dos sistemas que já existem; toda recusa tem registro | 6–8 PRs |
| F2 Intenção e requisitos | inventário de requisitos 100 % importado; todo REQ com tipo, dono, estado e enunciado | INT e NEED da semente; REQ um arquivo por requisito; os INV e G de `CONTRACT.md`, as 21 chaves de SLO e orçamento e as metas da arquitetura de referência importados como REQ; as decisões ligadas aos REQ que afetam; o trailer `Implements:`; estados derivados | inventário completo; nenhum REQ sem dono; `model check` recusa REQ sem enunciado | 6–8 PRs |
| F3 Arquitetura e decisões | todo REQ com ARC; toda unidade realiza um ARC; conformidade de reflexão medida | ARC um arquivo por elemento (sistema, capacidade, componente, contrato e porta), as capacidades e os contratos importados; os manifestos de unidade com os campos do Backstage; as 33 ADRs entram como D com estado e substituição (a ADR-24 substituída pela D-314, as do produto obsoletas); a confirmação de cada decisão aceita ligada à função de aptidão; a arquitetura de referência ligada aos REQ e aos ARC; as visões C4 e arc42 geradas | 0 unidades sem ARC; 0 decisões aceitas sem prova; reflexão medida | 7–9 PRs |
| F4 Construção e entrega | todo arquivo de código em uma unidade; achados de construção nunca sobem | os 368 arquivos atribuídos; `ruff` e `pyright` fixados, catraca nos arquivos mudados dentro dos 60 s; CHG como objeto, com estados derivados dos eventos da fila e do deploy; o escape atribuído ao sistema que o deixou passar | 0 arquivos sem unidade; catraca em bloqueio | 6–8 PRs |
| F5 Verificação | todo REQ com teste; seleção completa; adequação medida | TEST como objeto com nível e nível de integridade; `Verifies:`; a seleção derivada da execução (a rastreação, o rascunho de `padrao-metrics selection`) unida à declarada; contagem de casos por teste; cobertura do diff e mutação do diff pós-merge; quarentena de instáveis com dono e prazo | 0 pares sem seleção; adequação no painel | 7–9 PRs |
| F6 Validação | toda NEED com VAL; o teste de validação final existe | VAL para a escada da intenção (1.000 → 10.000 → 100.000 PRs/dia), as guardas da semente e os SLOs; o teste de validação final que mede, numa janela, se o sistema atende à necessidade; canário e SLO como validação contínua quando o motor tiver produção própria | toda NEED com VAL medida | 4–6 PRs |
| F7 Os sistemas de apoio | configuração, operação, medição, conhecimento e trabalho no modelo, cada um com medida | MEAS com o metadado da 15939; INC ligado a REQ/VAL e à mudança que conserta; premissas, lições e fricções como objetos; itens de trabalho ligados a REQ e ARC | conformidade L ou F nos cinco | 5–7 PRs |
| F8 Tudo nasce no modelo | a cadeia verificada em 100 % do inventário ativo; conformidade F em todos os sistemas | os geradores (`scripts/scaffold`) criam o objeto, as ligações e o teste juntos; o AGENTS.md vira um mapa curto gerado do modelo; as regras em aviso promovidas pela medida; o modelo aplicado a todo sistema novo que construirmos | critério de parada do programa | 4–6 PRs |

## Critério de parada
O programa para quando a cadeia verificada de ponta a ponta cobre 100 % do inventário de requisitos ativos (Daniel,
15/11 21:12 BRT, ao aprovar a revisão 2: era 95 %), todos os 15 sistemas estão em conformidade F, a taxa de escape está abaixo de 1 % numa janela de pelo menos 1.000 PRs
mergeadas, e nenhuma guarda piorou em relação à linha de base; ou quando um limite físico medido impede (por exemplo,
os 60 s do gate contra a checagem do modelo). O critério é registrado como decisão D-NNN na primeira PR da F1, com a
prova (o teste de `scripts/model measure`); custo-benefício e ruído de medida não param o programa. Com 100 %, um
requisito que não se consegue verificar tem duas saídas: ganha a sua verificação, ou é retirado (obsoleto ou
substituído) por uma decisão; os retirados saem do inventário ativo, como na DO-178C.
