# 00. Avaliação: o pedido, o escopo e o método

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

Projeto ARQ-REF (nível **projeto** do [método](../padrao/METODO.md): um resultado com começo e fim, prova binária).
Sessão nova, separada da [semente](../SEMENTE.md). Aberto em 04/11/2026 a partir do pedido de Daniel de 03/11/2026,
22:26 BRT, e da correção dele das 22:34 BRT.

Marcação usada em todos os documentos desta pasta: **[M]** medido no motor (com a fonte), **[F]** fonte externa
primária (o número entre colchetes aponta para [referencias.md](referencias.md)), **[I]** inferido (conta feita aqui,
reproduzível a partir das premissas escritas ao lado) e **[E]** estimativa ou hipótese, ainda sem prova.

## 1. O pedido

Nas palavras de Daniel, resumidas só no tamanho: o estado da arte da engenharia de hoje, na forma de uma arquitetura
completa de uma fábrica de software com IA, capaz de um volume enorme de PRs por segundo. A PR é a unidade de trabalho
e o padrão de performance. Com a arquitetura (os componentes, a forma, os adaptadores e os requisitos de cada um)
pronta, falta só o planejador e o conjunto de instruções para a IA. Ele não quer gastar interação produzindo esqueleto
que o estado da arte já fornece; quer gastar no que só A Torre pode produzir. São três fases: (1) o que a tecnologia de
hoje já fornece em arquitetura, que é este projeto; (2) a inovação da Torre; (3) buscar dinheiro.

**A meta mudou durante o pedido.** O texto original pedia 10^6 PRs/s. Às 22:34 BRT Daniel corrigiu: "Dez à nona,
bicho". A meta deste projeto é **10^9 PRs por segundo** (um bilhão por segundo), em média sustentada. Os degraus pedidos
são 1/min, 1/s, 10^3/s, 10^6/s e 10^9/s, sem refazer a arquitetura no caminho.

## 2. A intenção por trás do pedido

Dar à Torre um esqueleto que já está resolvido pelo mundo, com números, fontes e tetos, para que todo o esforço
seguinte vá para o planejador (gerar unidades úteis, independentes e do tamanho certo) e para as instruções da IA. O
esqueleto também tem que dizer, com conta, quanto custa cada degrau, porque a fase 3 é pedir dinheiro para ele.

## 3. Escopo

**Dentro.**

1. Problema e requisitos funcionais e não funcionais, com meta numérica por passo e por componente que, somadas,
   sustentam 10^9 PRs/s ([01-requisitos.md](01-requisitos.md)).
2. O motor de hoje medido contra as metas e os dados da Torre confirmados ou derrubados
   ([02-estado-atual.md](02-estado-atual.md)).
3. A arquitetura completa: sistemas, componentes, formas, portas e adaptadores, fluxos, estados, modelo de dados,
   falhas e recuperação, segurança e observabilidade, com diagramas ([03-arquitetura.md](03-arquitetura.md)).
4. Para cada componente: o estado da arte que já resolve, o que se compra pronto, o que se constrói e o teto real
   ([04-componentes.md](04-componentes.md)).
5. O orçamento de limites: cada gargalo com a conta e o custo de cada degrau
   ([05-orcamento-e-degraus.md](05-orcamento-e-degraus.md)).
6. O contrato que o planejador e o conjunto de instruções da IA têm que cumprir, inclusive a meta de amplificação
   ([06-contrato-planejador.md](06-contrato-planejador.md)).
7. As lacunas: a fronteira que ninguém atravessou e o que só A Torre pode responder ([07-lacunas.md](07-lacunas.md)).
8. As referências com links ([referencias.md](referencias.md)) e a verificação do desenho
   ([08-verificacao.md](08-verificacao.md)).

**Fora.** Código de produção. A lógica do planejador e o conteúdo das instruções da IA (aparecem só como componentes
com interface, contrato e metas). Rodar o gate ou o trem do motor. Criar recursos pagos. Tocar nas unidades ou nos
arquivos da semente, fechar ou mergear PRs dela e mexer nos rascunhos #3 e #41.

## 4. Definições operacionais

- **PR (canônica).** Uma mudança proposta a uma fonte de verdade de código, com identidade, base (o estado ao qual se
  aplica), conjunto de escrita (o que muda), conjunto de leitura (do que depende), o conteúdo da mudança (o diff ou a
  receita que o deriva), um veredito de verificação e um estado final. É um registro da fábrica, não necessariamente um
  objeto de PR num forge: no forge aparece uma visão dela.
- **Vazão.** PRs **mergeadas** por segundo na integração, numa janela móvel (a métrica da [semente](../SEMENTE.md), §3
  e §4). Uma PR rejeitada gasta capacidade e não conta. **Rendimento** y = mergeadas ÷ propostas.
- **Os cinco passos de toda PR** (dado de Daniel): (1) decidir o que mudar, (2) gerar, (3) verificar, (4) gravar e
  (5) coordenar (fila, despacho, estado). A vazão do sistema é a do passo mais lento.
- **Decisão.** O que a IA produz no passo 1 quando a fábrica opera em escala: uma transformação (programa, padrão ou
  especificação) com um predicado que escolhe os lugares onde se aplica. **Instância** é a decisão aplicada a um lugar;
  cada instância mergeada é uma PR.
- **Amplificação A.** PRs mergeadas por decisão de IA. Com D decisões por segundo, a vazão é D × A.
- **Degrau.** Uma vazão alvo: 1/min, 1/s, 10^3/s, 10^6/s, 10^9/s.

## 5. Método

Segue o caminho de projeto do [método](../padrao/METODO.md) (§2), que cobre as etapas de engenharia pedidas:

| Etapa de engenharia pedida | Passo do método | Onde |
|---|---|---|
| Problema | Avaliação | este documento |
| (pesquisa primeiro) | Pesquisa | as fontes de [04](04-componentes.md) e [referencias.md](referencias.md) |
| Requisitos | Avaliação e Análise | [01](01-requisitos.md), [02](02-estado-atual.md) |
| Desenho | Solução: uma escolha entre alternativas com custo, alcance e requisitos | [03](03-arquitetura.md), [04](04-componentes.md), [05](05-orcamento-e-degraus.md), [06](06-contrato-planejador.md) |
| Implementação | Fases | fora do escopo |
| Verificação do desenho | Verificação e Retrospectiva | [07](07-lacunas.md), [08](08-verificacao.md) |

Regras de trabalho: o estado da arte é o piso, nunca o teto (semente §5); nada de experimento cuja resposta já esteja na
literatura; todo número leva a marcação acima; uma decisão que os objetivos não fecham é tomada pela opção reversível,
registrada e reportada.

## 6. Dados da Torre a confirmar ou derrubar

Estimativas de ordem de grandeza que vieram com o pedido. Cada uma é julgada em [02](02-estado-atual.md) ou
[05](05-orcamento-e-degraus.md), com fonte.

| # | Dado | Onde é julgado |
|---|---|---|
| T1 | Hoje: trem serial, gate de ~10,5 s, teto ~360 PRs/h | 02 |
| T2 | O control plane na Cloudflare (Durable Objects, plano grátis) estourou a cota diária de leituras | 02 |
| T3 | API do Origin: 600 / 3.000 / 6.000 pontos/min (usuário / token de instalação / JWT de app); merge 10 pontos, leitura 1, escrita 5; orçamento de git não documentado | 02 |
| T4 | Escrita em lote com fonte de verdade distribuída: 10^6–10^7/s; nunca um commit por PR num branch só | 05 |
| T5 | Verificação incremental com cache por conteúdo, paralela: ~10^6/s ao custo de uma região de nuvem | 05 |
| T6 | Gate de 1 µs com unidades independentes: ~10^3 núcleos para 10^9/s | 05 |
| T7 | Geração por IA PR a PR: ~10^4–10^5/s no mundo todo | 05 |
| T8 | 10^9 só fecha se cada decisão da IA virar ~10^5–10^6 PRs aplicadas por programa | 05, 06 |
| T9 | Limite físico: um ciclo de clock é ~200–300 ps, então o piso de um gate fica entre ns e µs | 05 |

As reflexões de Daniel nesta conversa (o resto seria infraestrutura e financiamento; verificar unidade por unidade é
tranquilo quando as unidades são independentes; e se o gate fosse de microssegundos) são avaliadas em
[07](07-lacunas.md).

## 7. Prova de encerramento (binária)

O projeto termina quando todas estas afirmações são verdadeiras, conferidas em [08](08-verificacao.md):

1. Os sete entregáveis do pedido existem nesta pasta.
2. Todo requisito de [01](01-requisitos.md) aponta para pelo menos um componente de [03](03-arquitetura.md).
3. Todo componente tem estado da arte com fonte, o que se compra, o que se constrói, o teto real e a meta a 10^9.
4. A conta fecha: cada um dos cinco passos sustenta 10^9 PRs/s com utilização ≤ 75 %, e o custo por PR está escrito.
5. Cada degrau muda só adaptadores e parâmetros; nenhum componente entra ou sai entre 1/min e 10^9/s.
6. O contrato do planejador traz a amplificação mínima que 10^9 exige.

## 8. Registro do ambiente desta sessão

- O checkout veio do GitHub em `d6a8483eb`, da época antiga. Atualizado a partir do Origin conforme
  [RETOMAR §0](../RETOMAR.md): a CLI `origin` foi instalada pelo instalador público (SHA-256 conferido pelo próprio
  instalador), o git do repositório foi configurado com `origin auth setup-git --local`, e o branch da sessão avançou
  sem merge (fast-forward) para `058607f99`, a ponta de `mod/roadmap-integration` no Origin em 04/11/2026.
- O GitHub `openuniversity-si/open-university` respondeu 403 ao push: está arquivado (AGENTS.md). O remote `origin` aponta para o
  Origin, e o branch e a PR vivem lá.
- Nenhum recurso pago foi criado. O gate e o trem do motor não foram rodados.
