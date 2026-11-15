# PADRAO-DEV — solução

Uma escolha entre alternativas, cada uma com custo, alcance e requisitos (método §2, passo 4). As fases vêm depois da
escolha e são unidades de progresso dentro dela. Base: a [avaliação](avaliacao.md), a [pesquisa](pesquisa.md) e a
[análise](analise.md) (escape 10,9 %; causas C1 a C5).

## Alternativas

| | Alternativa | Custo | Alcance (causas) | Requisitos | Risco | Reversível |
|---|---|---|---|---|---|---|
| A1 | **Padrão em prosa.** Um documento de engenharia completo, organizado pelas áreas do SWEBOK, acrescentado ao brief de lançamento e ao AGENTS.md | baixo: 2–3 PRs | C1 só no papel; nada em C2–C5 | nenhum | alto: a pesquisa mostra que prosa de contexto custa mais de 20 % e não muda o sucesso (Gloaguen 2026; Anthropic: o que precisa acontecer sempre vai para hook) | sim |
| A2 | **Padrão como sistema verificável.** O padrão é um catálogo de regras, uma por arquivo, cada uma com fundamento, dono, checagem com testes próprios e modo (aviso → bloqueio); o que a máquina pode derivar deixa de ser escrito à mão (mapa teste → código, donos, agregados); a adequação dos testes e o escape são medidos como eventos, com catraca; o AGENTS.md vira um mapa curto gerado do catálogo | médio-alto: 6 fases, cerca de 30–45 PRs pequenas | C1–C5 | `strace` (já no executor), `coverage.py` e `ruff`/`pyright` fixados no toolchain; minutos de Actions depois do merge (repositório público: grátis) | médio: uma checagem com falso positivo trava o fluxo; mitigado pelo modo aviso com medida antes do bloqueio (Google, Sadowski 2018) | sim, por regra: cada regra volta a aviso num commit |
| A3 | **Redesenho ultrassegmentado.** Mover o código para `units/<id>/` físicos, um diretório por unidade com o seu teste, contrato e dependências locais, e quebrar os arquivos grandes antes de qualquer outra coisa | muito alto: ~800 arquivos movidos, ~60 PRs só de movimento | C5 inteira, C2 em parte | ferramenta de movimento com prova de comportamento igual | alto: a pesquisa não mostra que a segmentação em si sobe o sucesso do agente (Modular Mirage; Baldwin: o núcleo atravessa diretórios), e o movimento compete com a vazão | caro |
| A4 | **Adotar um sistema de build com inferência de dependências** (Pants ou Bazel) para derivar a seleção de testes, e Backstage para os scorecards | alto: migrar 214 wrappers, novo toolchain, daemon frio no executor do GitHub | C2 (só importações Python; não vê scripts chamados por subprocesso, que é como os nossos testes rodam), C3 em parte | Pants/Bazel fixados; o gate de 60 s com o daemon frio é incerto | alto | caro |

## Escolha
**A2, o padrão como sistema verificável.** É a única que alcança as cinco causas, e é o que a pesquisa encontrou em
todos os que operam em escala, humanos ou agentes: a regra é dado com checagem, a dependência é derivada, a adequação é
medida, a prosa fica para o julgamento rotulado. Ela aproveita o que já existe e funciona (o gate por plano, o cache por
conteúdo, as checagens derivadas de leitores e unidades, o registro de regras de 28/10, os princípios D-069, as decisões
como registros) em vez de começar de novo.

- **De A3 fica a medida, não o movimento.** A forma do código entra como função de aptidão: arquivos com unidade, tamanho
  e complexidade com catraca, unidades tocadas por PR medidas. Um arquivo grande é partido quando o histórico de
  co-mudança e os escapes apontam para ele, e não por regra geral. Isso testa a hipótese (a) com número.
- **De A4 fica a ideia, não a ferramenta.** A seleção derivada vem da nossa própria rastreação (`strace` da suíte
  completa depois do merge), que vê o que Pants não vê: os scripts que os testes chamam por subprocesso.
- **A1 fica como saída gerada.** O documento do padrão existe, mas é gerado do catálogo, nunca escrito à mão ao lado dele.

**O que o padrão passa a ser** (Padrão v9, `docs/padrao/v9/`, nasce na F1): o método de gestão (inalterado) mais um
catálogo de engenharia organizado pelas áreas que a pesquisa mostrou necessárias, cada uma um sistema gerido:

| Sistema | Dado | Checagem | Medida |
|---|---|---|---|
| Regras do padrão | um arquivo por regra (`id`, fundamento D-NNN, dono, checagem, testes da checagem, modo) | o gate recusa uma regra `block` sem checagem ou uma checagem sem teste | regras com checagem ÷ regras |
| Requisitos | decisões e requisitos de comportamento, um arquivo cada, com método de verificação; o teste declara o que verifica | rastreador gerado: requisito sem teste, teste citando requisito inexistente, prova sumida | requisitos com teste ÷ requisitos |
| Arquitetura | unidades com donos; dependências derivadas; funções de aptidão (portas, camadas, tamanho) | todo arquivo de código tem unidade; catraca de tamanho e complexidade | unidades por PR; co-mudança |
| Construção | lint e tipos Python, `shellcheck` | catraca: o número de achados por arquivo nunca sobe | achados por mil linhas |
| Testes | mapa teste → código derivado; inventário de casos | seleção = declarado ∪ medido; casos executados = casos esperados | completude da seleção; cobertura; mutação do diff; instabilidade |
| Entrega | escape e retrabalho como eventos; fila | uma PR de conserto nomeia a PR que conserta (`Fixes-PR:`) | taxa de escape (principal), vazão, gate |

Regras para toda mudança, que o padrão impõe: nada que se deriva é escrito à mão; uma lista que só cresce é um diretório
de arquivos, um por entrada, com o agregado gerado; toda regra nova chega com a sua checagem e os testes dela, em modo
aviso, e vira bloqueio quando a medida de falsos positivos permite.

## Fases
Cada fase tem auditoria técnica, planejamento, execução e verificação (método §2), num arquivo `phases/F<n>.md` aberto
quando a fase começa. A meta é sobre a métrica principal quando a fase a move; as outras metas são as guardas e
complementares que a fase existe para mover. A ordem segue o peso de cada causa nos escapes medidos (seleção 2,5;
comportamento sem requisito 2; teste fraco 1; efeito não local 1).

| Fase | Meta | O que muda | Critério de parada da fase | Tamanho |
|---|---|---|---|---|
| F1 Medir e catalogar | o painel inteiro medido por um comando; escape como evento | `scripts/padrao-metrics` (escape, completude da seleção, cobertura, regras com checagem, unidades por PR, exposição a conflito), o trailer `Fixes-PR:` e o evento de escape; o catálogo de regras um arquivo por regra, semeado das 49 recusas, dos princípios D-069 e das etapas do gate; `docs/padrao/v9/` com o mapa gerado; a decisão do programa registrada como D-NNN com a prova | o painel sai de um comando e bate com esta análise; toda recusa do gate tem registro | 5–7 PRs |
| F2 Seleção derivada | escapes da classe seleção = 0; pares teste × arquivo executado que a seleção não alcança: de 1.659 na amostra a 0 | a suíte completa pós-merge rastreia as leituras e publica o mapa medido; o gate seleciona por declarado ∪ medido; contagem de casos por teste com falha em zero ou abaixo do esperado; os `covers` deixam de ser escritos à mão (gerados do medido) | uma semana de `main` sem escape de seleção e sem par descoberto | 6–8 PRs |
| F3 Adequação e instabilidade | cobertura de `scripts/` e `infra/` medida a cada merge, com catraca por arquivo; mutação do diff medida | `coverage.py` fixado, cobertura pós-merge como evento; mutação dos arquivos do diff, assíncrona; o vermelho em lote verde sozinho vira registro de instabilidade com dono e prazo; os testes de tempo passam ao relógio injetado | as três medidas no painel, nenhuma caindo | 5–7 PRs |
| F4 Construção e forma | achados de lint e tipos nunca sobem; todo arquivo de código com unidade | `ruff` e `pyright` fixados, etapa de catraca no gate dentro dos 60 s (só arquivos mudados); os 368 arquivos atribuídos a unidades; catraca de tamanho; os pontos quentes medidos por co-mudança e partidos onde o escape aponta | catraca ativa; 0 arquivos sem unidade | 6–8 PRs |
| F5 Requisitos | todo requisito com teste; nenhuma prova sumida | requisitos de comportamento como registros, um por arquivo; o teste declara o que verifica; rastreador gerado no gate; as decisões entram no mesmo rastreio; `decision-next` funciona no GitHub | rastreador em bloqueio; escapes da classe comportamento = 0 numa semana | 4–6 PRs |
| F6 O padrão configura tudo | todo código novo nasce no padrão; taxa de escape < 1 % | geradores de unidade, teste e regra produzem código conforme; o AGENTS.md vira mapa curto gerado do catálogo; as regras em aviso promovidas a bloqueio pela medida; o padrão aplicado a cada sistema que construirmos (deploy, serviço, painel) | escape < 1 % em pelo menos 1.000 PRs, guardas sem piora | 4–6 PRs |

Depois de cada fase: medir o painel inteiro, responder na PR se o objetivo melhorou ou só o número (D-133), redesenhar
as fases seguintes se a medida mudou a ordem das causas.

## Critério de parada
O programa para quando a taxa de escape fica abaixo de 1 % numa janela de pelo menos 1.000 PRs mergeadas, com todas as
guardas iguais ou melhores que a linha de base, ou quando um limite físico medido impede (o tempo do gate de 60 s contra
a seleção que a completude exige, por exemplo). O critério é registrado como decisão D-NNN na primeira PR da F1, com a
sua prova (o teste de `scripts/padrao-metrics`); custo-benefício e ruído de medida não param o programa.
