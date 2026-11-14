# 08. Verificação do desenho e retrospectiva

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

O passo "verificação" do [método](../padrao/METODO.md) (§2): o projeto entregou o que prometeu? Verificar não é medir:
aqui cada afirmação da prova de encerramento ([00 §7](00-avaliacao.md#7-prova-de-encerramento-binária)) é conferida com
a evidência. Depois vêm as checagens de consistência, os riscos que restam e a retrospectiva.

## 1. A prova de encerramento

| # | Afirmação | Evidência | Resultado |
|---|---|---|---|
| 1 | Os sete entregáveis existem | 1 requisitos: [01](01-requisitos.md); 2 arquitetura: [03](03-arquitetura.md); 3 componentes: [04](04-componentes.md); 4 orçamento e degraus: [05](05-orcamento-e-degraus.md); 5 contrato: [06](06-contrato-planejador.md); 6 lacunas: [07](07-lacunas.md); 7 referências: [referencias.md](referencias.md); mais a análise ([02](02-estado-atual.md)) e o resumo ([README](README.md)) | **verdadeira** |
| 2 | Todo requisito aponta para um componente | matriz da seção 2 abaixo: os 18 RF e os 12 RNF têm pelo menos um componente | **verdadeira** |
| 3 | Todo componente tem estado da arte com fonte, o que comprar, o que construir, teto real e meta a 10^9 | as seis tabelas de [04](04-componentes.md): 29 de 29 linhas preenchidas; C02 e C03 têm como estado da arte o que mais se aproxima, porque são a inovação da Torre | **verdadeira** |
| 4 | A conta fecha: cada passo sustenta 10^9 com ρ ≤ 0,75 e o custo por PR está escrito | [05 §2](05-orcamento-e-degraus.md#2-o-gargalo-de-cada-passo-com-a-conta) e §5: todos os passos têm capacidade de projeto de 1,33× a vazão; custo de 1,7 a 6 × 10^-8 por PR, dentro de RNF-04 | **verdadeira, com as três condições da seção 3** |
| 5 | Cada degrau muda só adaptadores e parâmetros | [05 §6](05-orcamento-e-degraus.md#6-o-que-muda-de-um-degrau-para-o-outro) e a tabela de portas de [03 §5](03-arquitetura.md#5-portas-e-adaptadores): os 29 componentes existem em todos os degraus; o de 1/min é o motor de hoje com a decisão de um lugar só | **verdadeira** |
| 6 | O contrato do planejador traz a amplificação mínima | PC-02 e PC-04 em [06](06-contrato-planejador.md#4-os-requisitos-e-as-metas): A ≥ 10^6 com T_d ≤ 10^5, ≤ 0,15 token de IA por PR mergeada | **verdadeira** |

O projeto está encerrado: o resultado existe.

## 2. Rastreabilidade dos requisitos

| Requisito | Componentes | Requisito | Componentes |
|---|---|---|---|
| RF-01 intenções | C01, C05 | RNF-01 vazão | todos; [05 §2](05-orcamento-e-degraus.md) |
| RF-02 decisões | C02, C03, C06, C07 | RNF-02 latência | C22, C25, C18, C14 |
| RF-03 enumerar lugares | C04 | RNF-03 qualidade | C10–C14, C27 |
| RF-04 gerar por programa | C08, C09 | RNF-04 custo | C05, C27; [05 §5](05-orcamento-e-degraus.md) |
| RF-05 certificar | C10, C15 | RNF-05 disponibilidade | C16, C19, C29 |
| RF-06 V0, V1, V2 | C11, C12, C13 | RNF-06 escala horizontal | células (C26, C29) |
| RF-07 ondas | C22, C14 | RNF-07 segurança | C07, C28 |
| RF-08 validação otimista | C24, C25 | RNF-08 observabilidade | C27 |
| RF-09 gravar | C16, C25 | RNF-09 determinismo | C08, C09 |
| RF-10 snapshots e cortes | C17, C18 | RNF-10 energia | [05 §5](05-orcamento-e-degraus.md) |
| RF-11 V3 e rollback | C14, C22 | RNF-11 portabilidade | as portas de [03 §5](03-arquitetura.md) |
| RF-12 espelho de forge | C20 | RNF-12 cota e plano | C05, C20; [05 §6](05-orcamento-e-degraus.md) |
| RF-13 medir de fora | C27 | | |
| RF-14 admissão e contrapressão | C05, C21, C23 | | |
| RF-15 sandbox e proveniência | C07, C28 | | |
| RF-16 degraus por adaptador | todas as portas | | |
| RF-17 proveniência e dependência | C19, C22, C28 | | |
| RF-18 caminho A = 1 | C02, C07, C13, C20 | | |

## 3. Checagens de consistência entre os documentos

As metas de [01](01-requisitos.md) contra as contas de [04](04-componentes.md) e [05](05-orcamento-e-degraus.md):

| Item | Meta (01) | Conta (04, 05) | Resultado |
|---|---|---|---|
| Tokens de IA | ≤ 1,5 × 10^8/s | 1,1 × 10^8/s | cabe |
| Núcleos da verificação | ≤ 2 × 10^6 | ~1,8 × 10^6 | cabe |
| Ledger | 1,33 × 10^9 anexos/s, ≤ 128 B | 128 GB/s de carga, 170 GB/s de capacidade | cabe |
| Workflows | ≥ 6,7 × 10^4 transições/s | 5 × 10^4/s de carga | cabe |
| Custo da IA por PR | ≤ 2 × 10^-8 | 2 × 10^-9 (Haiku 5.5) a 3 × 10^-8 (Sonnet 5.5 a preço de lista) | **cabe com lote ou frota própria** (1,5 × 10^-8 com o desconto de lote) |
| Custo da verificação por PR | ≤ 1,5 × 10^-8 | 1 × 10^-8 em spot; 2,2 × 10^-8 sob demanda | **cabe em spot ou com compromisso de uso** |
| Custo de gravar por PR | ≤ 5 × 10^-9 | ~1 × 10^-9 de armazenamento + 2,6 a 5,1 × 10^-9 de réplica entre domínios | **cabe só com a réplica a ≤ US$ 0,01/GB** (mesma região ou datacenter próprio) |
| Custo de coordenar por PR | ≤ 2 × 10^-9 | ~1,6 × 10^-9 | cabe |
| Total | ≤ 10^-7 | 1,7 a 6 × 10^-8 | cabe |

**As três condições de fechamento** saem daí e passam a fazer parte do desenho: (1) a IA usa lote ou frota própria;
(2) a verificação roda em capacidade spot ou com compromisso de uso; (3) a réplica do ledger entre domínios de falha fica
na mesma região ou em datacenter próprio.

**Lei de Little em cada passo a 10^9** [I]: o pipeline de instância com p99 ≤ 1 s tem até 10^9 instâncias em voo, de
128 B a 1 KB cada, 0,13 a 1 TB de memória espalhada pelas células, o que cabe. Com certificação de 5 min, expansão de
10 min e observação de 15 min, ficam ~1,8 × 10^6 decisões em voo, coerente com C22 (≥ 10^6 workflows em voo).

**Um acoplamento que o desenho revelou** [I]: os lugares em voo são D × A × T_exp = 10^9 × 600 s = 6 × 10^11. Para
que a sobreposição entre decisões em voo fique ≤ 1 % (PC-06), o corpus útil precisa ter muito mais que 6 × 10^11
lugares; se tiver 10^13, ~6 % estão em voo e a expansão precisa cair para ~100 s. O tamanho do corpus, que é a pergunta
da demanda ([07 §2](07-lacunas.md#2-o-que-só-a-torre-pode-responder)), decide a latência de expansão.

**Diagramas.** Os 8 diagramas mermaid desta pasta passam no parser do mermaid 11.4.1, rodado num Chromium sem tela.

**Referências.** Todo identificador citado nos documentos existe em [referencias.md](referencias.md) (conferido por
script). Das 163 entradas, 80 foram lidas na página (no site ou na fonte oficial no GitHub), 74 só no trecho da busca e 9
são conceitos ou documentos do repositório. Os números que dimensionam a fábrica e vieram só de trecho são: o volume de
tokens do Google [A14], a escala do Kafka no LinkedIn [C7], o Scribe [C11], o pico do Spanner [C16] e do DynamoDB [C18],
e as fontes de verificação do grupo V. Nenhum deles muda a ordem de grandeza de uma conclusão: em cada caso há um número
lido na página que aponta para o mesmo lado (por exemplo o FoundationDB [S22] para o banco, o estoque de chips [A16] e a
frota da DeepSeek [A1] para a inferência).

## 4. Riscos que restam no desenho

| Risco | Efeito | O que o mitiga |
|---|---|---|
| O planejador não chega a A ≥ 10^6 com T_d ≤ 10^5 | o custo de IA a 10^9 passa de 10^-7 por PR | é a pesquisa da fase 2; cada degrau mede A e T_d com o mesmo instrumento ([06 §6](06-contrato-planejador.md#6-como-o-contrato-é-medido)) |
| A certificação custa mais que 10^3 núcleo·s por decisão | a verificação passa de 10^7 vCPU | classes de certificado mais baratas; mais amplificação por decisão |
| Não há trabalho útil para 10^9 | a fábrica fica ociosa ou infla PRs | a métrica de utilidade (PC-15, PC-16) e a pergunta da demanda ([07 §2](07-lacunas.md#2-o-que-só-a-torre-pode-responder)) |
| Defeitos escapam acima de 10^-6 por PR | retrabalho e rollbacks em massa | prova em vez de amostra (L5); ondas com parada; rollback por decisão |
| Números só de trecho estavam errados | uma ordem de grandeza muda | as conclusões que dependem deles têm um número lido na página do mesmo lado (seção 3) |

## 5. Retrospectiva

**O que aconteceu.**

- O checkout veio do GitHub arquivado (`d6a8483eb`, 934 commits atrás). Instalar a CLI `origin` pelo instalador público
  e configurar o git do repositório, como o [RETOMAR §0](../RETOMAR.md) descreve, funcionou; o auxiliar de credencial
  pediu o token trocado em `CURSOR_AUTH_TOKEN`, também como o RETOMAR prevê.
- O fast-forward para a base do Origin rodou o hook `post-merge` antes de o remote `origin` apontar para o Origin; o
  push guard tentou empurrar ao GitHub arquivado, levou 403 e abriu sozinho o incidente I-a130067c. Depois da troca de
  remote, os oito pushes foram para o Origin, um commit por push. O incidente não entrou nesta PR (está fora do escopo e
  a causa já foi resolvida).
- Daniel trocou a meta de 10^6 para 10^9 enquanto a pesquisa rodava; como os requisitos ainda não estavam escritos, a
  troca custou só o briefing da pesquisa.
- A pesquisa rodou em cinco subagentes em paralelo. O egress bloqueou a maior parte dos sites primários e o limite de
  200 buscas por turno, compartilhado entre eles, acabou; a saída foi ler as fontes oficiais nos repositórios do GitHub
  (o único host de fontes liberado), o que deu 80 entradas lidas na página.

**O que se aprendeu.**

1. Em todo degrau acima de 1/s o gargalo é a amplificação do planejador. É a mesma restrição que o motor mede hoje (a
   oferta de unidades prontas e independentes): a arquitetura confirma que o primeiro gargalo da Torre é o certo.
2. O forge é um sistema de ritmo humano (o GitHub recomenda até 1 merge por minuto por repositório [S14]) e sai do
   caminho crítico entre 0,1 e 1 PR/s.
3. O gate de microssegundos é consequência da certificação por decisão, não substituto dela.
4. Um invariante só resume o lado da IA: **tokens de IA por PR mergeada**, ~10^6 hoje, ≤ 0,15 a 10^9.

**O que muda no padrão** (propostas; nenhuma aplicada por esta PR):

1. Medir desde já, em `scripts/flow-metrics`, a amplificação e os tokens por PR mergeada (o motor já tem
   `scripts/usage --tokens --per-pr`); assim a escada de 1/min a 10^9 usa um instrumento só.
2. Um brief de pesquisa nomeia o egress liberado e o orçamento de buscas da sessão, como o retro do ORIGIN-FINISH já
   pediu para provas ao vivo.
3. No [RETOMAR §0](../RETOMAR.md), trocar o remote antes de qualquer operação git que rode hooks (um merge ou um
   fast-forward), para o push guard nunca mirar o GitHub arquivado.
