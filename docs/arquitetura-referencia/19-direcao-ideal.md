# 19. A direção ideal: da intenção ao trabalho

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Na fronteira de 12:19** ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)): gestão (fase 2) e liderança
> (fase 3). É o nosso modelo de gestão, um entre os possíveis: outro pode não ter meta, objetivo nem aposta (Daniel,
> 12:14), e nada daqui entra na infraestrutura. A intenção, a governança e a métrica-norte são da liderança. Insumo
> das duas fases, sem implementação agora.

A direção é o subsistema que existe para **haver sempre próximo trabalho, valioso e bem especificado**, sem perguntar a
ninguém ([18 §5](18-planta-geral.md#5-o-contrato-de-cada-parte)). Este documento a redesenha a partir da intenção de
origem (Daniel, 04/11: "janelas mais longas de autonomia dos agentes"), tratando o que existe (o METODO, o padrão v8, a
SEMENTE, os documentos 06, 16 e 17) como evidência, não como verdade.

## 1. O que falha na direção de hoje

1. **A direção só existe no diagrama.** Portfólio, programa, projeto e fase estão no METODO e no modelo do 16, sem tabela,
   estado nem dono guardado ([16 §3](16-modelo-de-dominio.md#3-onde-ele-falha), falha 2). A auditoria do passo zero
   (04/11, [21 §5](21-revisao-geral.md#5-os-comandos)) contou: o portfólio só aparece no METODO, medido em commits por dia;
   nenhum projeto existe; há 8 pastas de programa, o código pede em cada uma brief, auditoria, plano e retrospectiva
   (`config/registry/coordinator.json`), e a do VAZÃO, o programa ativo, não tem nenhum dos quatro.
2. **Cinco definições de programa**: "um conjunto de projetos" (METODO), "um conjunto de PRs" (padrão v8), "um grafo de
   PRs" (o documento do coordenador e `scripts/lib/program.py`), "terminado quando toda unidade mergeou e a meta foi
   atingida" (`scripts/program-gate`) e "um ciclo PDCA sobre uma fila de unidades" (o programa VAZÃO). A chave `F<n>` tem
   três sentidos: a linha da fila do VAZÃO (até F133), o arquivo de fase (F1 a F11 no gate-speed) e a unidade do
   fluxo-amplo; F2 é as três coisas, e `scripts/lib/deliver.py` trata todo `F<n>` num título de PR como linha da fila.
3. **O planejador não é entidade.** Quem escolhe o próximo trabalho são sessões de coordenação de vida curta, e a escolha
   delas (o que foi considerado, por que isto, o que se esperava) não fica em lugar nenhum: não dá para medir se elas
   escolhem bem. E a faixa recebe trabalho de quatro lugares, conforme o documento que se lê: a fila, o grafo do
   coordenador, um gerente de domínio ou a lane A ([21 §6](21-revisao-geral.md#6-as-instruções-e-os-prompts)).
4. **"Decisão" e "intenção" têm dois sentidos cada**: a decisão de Daniel (D-NNN) e a escolha do dia a dia; a intenção
   da semente e o campo `intents` do manifesto de unidade.
5. **A métrica não mede a intenção de origem.** A semente mede PRs por segundo; a intenção de origem é a janela de
   autonomia. O METODO ainda fala em commits por dia.

## 2. Os níveis: quais ficam e quais saem

Cada nível do METODO julgado contra a intenção: ele ajuda a haver próximo trabalho valioso sem perguntar a ninguém?

| Nível | Fica? | Por quê |
|---|---|---|
| Intenção | **fica**, com versão e a trava | é a única fonte do porquê, e só Daniel a valida |
| Portfólio | **sai como entidade** | um portfólio é um degrau da escada da intenção (1.000, 10.000, 100.000 por dia): um número-alvo da intenção, não um contêiner de programas |
| Programa | **fica, com uma definição só: um objetivo medido** | uma métrica, um alvo, guardas, um dono; persiste até o alvo ser atingido |
| Projeto | **vira aposta** | um resultado com prova binária e, além disso, o efeito esperado na métrica do objetivo, um orçamento (o apetite) e um veredito depois: a aposta é uma hipótese que se confirma ou não |
| Fase | **sai como entidade** | dentro de uma aposta, os processos formam um grafo, como os itens dentro de um processo ([17 §3](17-ciclo-do-processo.md#3-o-plano-de-commits-como-dado)); um marco é um subconjunto do grafo com verificação, não um nível; a colisão da chave `F<n>` com o arquivo de fase some com ele |
| Processo | **fica** | é a PR ([17](17-ciclo-do-processo.md)) |
| Operação | **fica, como evento** | o ato registrado |

Ficam quatro níveis com dono e estado: **intenção → objetivo → aposta → processo**, e a operação como registro.

## 3. As entidades da direção

| Entidade | Por que existe | Identidade | Estados | Relações | Quem cria | Quem consome | O que se mede |
|---|---|---|---|---|---|---|---|
| **Intenção** | o porquê de tudo; o que a fábrica otimiza | `INT-v<n>` | `proposed` → `validated` (só Daniel) → `superseded` | define a métrica-norte e o degrau-alvo | Daniel; a sessão rascunha | o planejador, a medição | a métrica-norte (seção 7) |
| **Objetivo** (o programa) | traduz a intenção em alvos medidos | `PRG-<slug>` | `proposed` → `active` → `achieved` ou `abandoned`, com retrospectiva | pertence a uma versão da intenção; tem apostas | o planejador, sem pedir a ninguém, dentro da intenção | o planejador, a medição, o aprendizado | uma métrica de entrada contra o alvo, que se confere sem discussão, e as guardas; a classe `committed` ou `aspirational` (seção 7) |
| **Aposta** (o projeto) | um trabalho limitado que deve mover um objetivo | `BET-<n>` | `proposed` → `accepted` → `active` → `delivered` (a prova binária) → `evaluated` (efeito confirmado ou refutado); `cancelled` quando o apetite acaba, nunca estendida em silêncio | um objetivo; os processos dela, em grafo; a escolha que a abriu; a suposição mais arriscada | o planejador | o trabalho (os processos), o aprendizado (o veredito) | custo contra o apetite, efeito medido na métrica, tempo |
| **Escolha** do planejador | torna o julgamento do planejador auditável e aprendível | `CH-<n>` | `recorded` → `reviewed` (o resultado comparado com o esperado) | duas opções ou mais, cada uma com valor e viabilidade estimados; a aposta ou os processos que gerou; a premissa em que se apoia | o planejador | o aprendizado (a qualidade do planejador); Daniel, na auditoria | acerto (apostas que moveram a métrica), erro de estimativa de valor e de viabilidade |
| **Processo** | a unidade que vira uma PR | `F<n>` | os de [17 §4](17-ciclo-do-processo.md#4-as-máquinas-de-estado-e-os-eventos) | uma aposta, ou o objetivo quando é manutenção dele | o planejador | o trabalho | os de [17](17-ciclo-do-processo.md) |

**A escolha** guarda: as entradas que o planejador leu (a lacuna da métrica, a restrição atual, a fila, as lições
abertas), as opções que considerou com o valor e o custo estimados de cada uma, a opção escolhida, o efeito esperado e
quando ela deve ser revista. É o registro dado, leitura, crença e aposta do Spotify [N6], com a crença guardada como
premissa (`P-NN`). Sem isso não dá para saber se o planejador escolhe bem, nem para ensiná-lo.

**Os orçamentos se encaixam.** O apetite da aposta (tokens, tempo de relógio e dinheiro) limita o dos processos dela, que
limita o de cada tentativa; um orçamento delegado nunca passa o do pai [N16], e toda sessão vê, a cada rodada, quanto
usou e quanto resta [N15]. Acabado o apetite, a aposta é cancelada e volta ao planejador como uma escolha nova, com o que
se aprendeu; não há extensão automática [N5].

## 4. O planejador

O planejador é um **workflow**, não uma sessão longa. Ele acorda por evento:

- a fila de trabalho pronto cai abaixo de algumas horas de trabalho;
- uma métrica ou uma guarda sai do alvo, ou a restrição muda;
- uma aposta é entregue ou avaliada;
- uma versão nova da intenção é validada.

A cada vez, ele roda uma sessão curta de agente no papel de planejador, com o pacote de instruções desse papel tirado do
padrão (seção 5), e o produto dela é dado: escolhas, apostas e processos com o contrato completo, que a admissão confere
([12 §2](12-unidade-e-sessoes.md#2-o-contrato-da-unidade-de-trabalho)). Ele nunca pergunta; o que só uma pessoa alcança
vira pedido à Torre (seção 6), que bloqueia só o que depende dele.

**Como ele pontua.** Cada opção recebe o valor esperado (quanto move a métrica de entrada do objetivo) vezes a
viabilidade (a chance de mergear de primeira, estimada das tentativas parecidas), como em [N13], e não só o valor; a linha
de trabalho que já gerou muitas apostas perde peso, para não gastar tudo na mesma ideia [L19]. Ele recebe o que foi feito e
o que falhou por ser difícil demais, e só propõe trabalho que dá para verificar com o que o sistema vê [L17]. Uma fila sem
dono não acumula: a proposta que não entrou expira e é reproposta se ainda valer [N5].

**Na escala.** A 1 PR/min, ~60 processos por hora: uma rodada do planejador a cada meia hora, com algumas dezenas de
processos, basta. A 1 PR/s são 3.600 por hora, e o planejador não escreve processo por processo: escreve apostas que
geram processos em série, por modelo de transformação, a amplificação de [06](06-contrato-planejador.md). A forma é a
mesma; muda quanto trabalho cada escolha gera.

## 5. O padrão

O padrão é **o jeito de fazer que todo agente segue**: as regras, as instruções e os prompts de cada papel, os modelos
de documento e a configuração das ferramentas. Hoje ele está espalhado: o padrão v8, o AGENTS.md, o CLAUDE.md, o
RETOMAR, os documentos de lane e de coordenação e os briefs de lançamento, que divergem entre si e do código
([17 §6.1](17-ciclo-do-processo.md#61-o-que-falha-hoje), falha 9). A auditoria do passo zero contou sete regras escritas
que o código desmente e nove pares de regras que se contradizem ([21 §6](21-revisao-geral.md#6-as-instruções-e-os-prompts)).

No ideal:

| Parte | O que é |
|---|---|
| **Versão do padrão** (`PV-<n>`) | um conjunto de regras com uma versão vigente; versões candidatas só existem dentro de um experimento do aprendizado ([20](20-sistema-de-aprendizado.md)) |
| **Regra** | id, texto, a razão (a decisão ou a lição de onde veio), o papel e a etapa a que se aplica, a métrica que deve melhorar e a suposição que ela carrega sobre o que o modelo não faz sozinho [L9], que o aprendizado testa de novo quando o modelo muda |
| **Pacote de instruções por papel** | gerado das regras: o planejador, a sessão que executa um processo, o coordenador; com orçamento de tamanho, porque o contexto do agente é um recurso medido |
| **Vínculo com a tentativa** | toda tentativa registra a versão do padrão com que rodou; é o que permite comparar versões |

O padrão muda por dois caminhos só: o aprendizado adota uma versão que um experimento mostrou melhor, ou Daniel decide
uma regra que é dele (dinheiro, pessoas, a intenção). Uma regra sem razão ou sem métrica não entra, e duas regras que
se contradizem são um erro que o teste do padrão recusa.

## 6. A governança

| Entidade | O que é | Quem cria |
|---|---|---|
| **Decisão de Daniel** (`D-NNN`) | uma regra, um gasto ou uma mudança da intenção, com o teste que a prova; o número alocado pelo banco | Daniel; a sessão registra com as palavras dele |
| **Premissa** (`P-NN`) | uma suposição com estado (`inferred` … `confirmed`, `refuted`); é o alvo do aprendizado de laço duplo | o sistema, com a fonte |
| **Pedido à Torre** | o que só as capacidades de Daniel alcançam, tipado pela lista fechada (login, credencial, dinheiro, pessoas, cota); nunca para o resto | o sistema |
| **Limite** | a lista fechada de paradas, os orçamentos (o teto de US$ 60 da AWS, o de agentes) e a trava da intenção, como dado | Daniel |

A governança mede as paradas por classe, que são o denominador da janela de autonomia, o tempo de resposta da Torre e os
pedidos que bloquearam algum trabalho, que devem ser só os processos que dependem deles.

## 7. A medição da direção

**Uma proposta para Daniel** (a trava da intenção: só ele valida): medir a intenção de origem de forma direta.

| Medida | Definição | Por que |
|---|---|---|
| **Janela de autonomia** (a métrica-norte proposta) | o tempo entre duas paradas que exigem alguém de fora; a mediana e o percentil 10 por dia | é a intenção de origem dita como número; o percentil 10 pega as janelas curtas, que são as que doem |
| Fração de PRs sem intervenção | as PRs mergeadas em cujo ciclo inteiro ninguém de fora precisou agir | a janela vista por unidade de trabalho |
| Intervenções por 100 PRs, por classe | as paradas contadas pelas classes de [18 §1](18-planta-geral.md#1-a-intenção-como-ponto-de-partida) | diz qual subsistema atacar |
| Vazão | PRs por segundo, a escada da semente | fica como medida de capacidade |
| Guardas | retrabalho, custo por PR mergeada (tokens e infraestrutura), cota usada, vermelho e flake na fila | a vazão não se infla e a janela não se compra com qualidade |

Com janelas longas, a vazão sai contínua: é a "continuidade, não rajadas" da semente. Trocar a métrica da seção 3 da
semente pede uma PR `intencao:` com a linha de aprovação de Daniel; este documento só propõe.

**Duas classes de objetivo.** Um objetivo `committed` espera o alvo inteiro, e errar pede explicação: é a classe das
guardas e dos limites (o teto de US$ 60, a cota). Um `aspirational` espera cerca de 70 % do alvo, com variância alta, e
continua no ciclo seguinte enquanto não chega: é a classe do degrau da escada [N1] [N2]. Só o erro de um `committed` abre
uma retrospectiva obrigatória ([20 §4](20-sistema-de-aprendizado.md#4-a-retrospectiva-refeita)).

## 8. O que o estado da arte ensina à direção

| Lição | Fonte | O que muda no desenho |
|---|---|---|
| O objetivo diz o quê; o resultado-chave mede o como, de um jeito que no fim se responde "fiz ou não fiz" sem discussão | Doerr [N3], Grove [N4] | a métrica do objetivo é conferida por consulta, nunca por julgamento; a prova da aposta é binária ([12 §2](12-unidade-e-sessoes.md#2-o-contrato-da-unidade-de-trabalho)) |
| Metas comprometidas esperam 1,0 e o erro pede explicação; as aspiracionais esperam ~0,7 e continuam | Google [N1] [N2] | as duas classes de objetivo (seção 7) |
| As metas da diretoria da Amazon são quase todas de entrada, porque a saída "can't be directly or sustainably manipulated"; julgadas como cumpridas ou não, e ~70 % se cumprem | Bryar e Carr [N10] | o objetivo mira uma métrica de entrada (paradas por classe, tempo de ciclo, fração que mergeia de primeira), e a janela de autonomia é a saída que elas movem |
| A métrica-norte é um resultado, uma variável dependente, com 3 a 5 entradas independentes | Amplitude [N7] | uma métrica-norte (a janela, seção 7) e poucas entradas por objetivo; o planejador escolhe sobre as entradas |
| O apetite é um orçamento de tempo fixo com escopo variável; sem extensão por padrão, a aposta perde no máximo um ciclo; não há backlog: só propostas recentes competem | Shape Up [N5] | o apetite e o disjuntor da aposta (seção 3); a proposta que não entra expira (seção 4) |
| Apostas defendidas por dados, leitura, crença e aposta, ordenadas pelas crenças e pela métrica-norte, em agora, próximo e depois | Spotify [N6] | o registro da escolha (seção 3), com a crença como premissa testada pelo laço duplo ([20 §3](20-sistema-de-aprendizado.md#3-o-ciclo-da-evidência-à-mudança-medida)) |
| Começar pela experiência de quem usa e trabalhar para trás, num texto de uma página | Amazon [N8] | a aposta começa pelo resultado visível, num contrato de tamanho limitado, antes de qualquer processo |
| Um dono só, em tempo integral numa iniciativa, alinhado em objetivo e métrica antes de delegar; "fire and forget" é arriscado | Bryar e Carr [N9] | cada objetivo e cada aposta têm um dono só; a delegação leva o objetivo e a métrica fixados |
| Um resultado no topo; oportunidades; soluções; testes de suposição; "há mais de um jeito de atacar esta oportunidade?"; testar primeiro a suposição mais arriscada | Torres [N11] | a escolha registra duas opções ou mais, e a aposta nomeia a suposição mais arriscada, testada primeiro e pelo caminho mais barato |
| As entregas são o nível menos importante do mapa e saem quando não contribuem; as métricas de impacto se revisam com frequência | Adzic [N12] | o processo é o nível descartável: o que não mostra efeito na aposta é cortado; a medição liga processo, aposta e objetivo |
| Um currículo automático propõe uma tarefa por vez, nem difícil demais nem repetida, sabendo o que foi feito e o que falhou, e evita tarefas que não dá para verificar com o que se vê; um crítico julga o sucesso | Voyager [L17] | as entradas do planejador (seção 4) e a verificação por outro papel |
| Cada habilidade pontuada pela utilidade vezes a viabilidade | SayCan [N13] | a pontuação valor × viabilidade (seção 4) |
| Cada ideia com notas de interesse, viabilidade e novidade, e o custo por artigo medido | AI Scientist [N14] | as notas do planejador são dado gravado e comparado com o resultado; o custo por aposta é medido |
| O pai escolhido com peso pela nota e pelo inverso do número de filhos | DGM [L19] | a exploração balanceada do planejador (seção 4) |
| Orçamento maior sozinho não ajuda, porque falta ao agente noção do orçamento; um rastreador mostra o usado e o restante a cada rodada | Liu et al. [N15] | toda sessão, a do planejador inclusive, vê o orçamento a cada rodada |
| Um contrato junta entradas e saídas, limites de recurso, prazo e critério de sucesso; o orçamento proíbe, o critério obriga, e o delegado respeita o do pai | Ye e Tan [N16] | os orçamentos encaixados (seção 3) e os quatro campos no contrato do processo |

Nenhuma dessas fontes mede a janela de autonomia; a escada de horizonte do METR [L1] [L2] mede quanto tempo um agente
trabalha sozinho numa tarefa, não numa fábrica. A métrica-norte proposta na seção 7 é, portanto, uma extrapolação, e o
aprendizado ([20](20-sistema-de-aprendizado.md)) deve tratá-la como premissa até ela ser medida.
