# 02. Análise: o motor de hoje medido e os dados da Torre

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

O passo "análise" do [método](../padrao/METODO.md) (§2): o estado atual medido e as causas. Cada número traz a
marcação de [00](00-avaliacao.md). As medidas [M] desta sessão foram tiradas em 04/11/2026 entre 01:30 e 02:05 UTC, só
com leitura, sem rodar o gate nem o trem.

## 1. O motor de hoje nos cinco passos

| Passo | Como o motor faz hoje | Medida |
|---|---|---|
| 1. Decidir | a sessão gerente e coordenadores de domínio de vida curta escrevem unidades na fila ([fila](../programs/vazao/fila.md)); cada unidade vira uma ou mais PRs escritas por IA, uma a uma (A = 1) | em 03/11 a fila ficou sem linhas livres: a oferta de unidades prontas e independentes era a restrição [M, [sistema](../programs/vazao/sistema.md) §1] |
| 2. Gerar | uma lane (sessão longa do Claude Code) escreve 1 a 8 commits no seu worktree | ~50 mil tokens não cacheados e ~14 mil de saída por PR; 8 PRs em 71 min com 1 a 2 frentes (6,8 PR/h) [M, sistema §1]; com ~94 % dos tokens de uma sessão de agente sendo leitura de cache [A9], são ~10^6 tokens processados por PR [I], a mediana que a literatura mede para tarefas de agente de 1 a 16 h [A10, A11] |
| 3. Verificar | pre-push local (5 a 27 s) e `scripts/gate-dev` no head exato, na caixa de 4 CPUs, uma suíte por vez | gate do head ao merge em 84 merges de 03/11: p25 87 s, mediana 105 s, p75 153 s; 13,3 % dos gates vermelhos; 1,25 gates por merge [M, sistema §1]; a suíte sozinha leva 113 s e três simultâneas levam 346 s cada [M, idem]; o programa gate-speed levou o gate de 169 s a 0,99 s com os resultados compartilhados e a ~74 s sem cache algum [M, [retro](../programs/gate-speed/retro.md)] |
| 4. Gravar | `scripts/deliver` traz a base, julga de novo se ela andou e faz `origin pr merge --expect-head` com merge commit em `mod/roadmap-integration` | melhor hora fechada: 41 PRs (03/11 18:00, 0,0114 PR/s); horas de 03/11 entre 16:00 e 21:00: 15 a 41 PRs; últimos 20 merges: 0,0028 PR/s [M, `scripts/flow-metrics`, 04/11 01:56 UTC] |
| 5. Coordenar | eventos pelo forge e pelo log em git-ref no Origin (D-300); a trava da caixa serializa os gates; o trem está parado até a VM crescer; o control plane (Worker e um Durable Object na Cloudflare) ficou só com o que fala com o Origin | o control plane respondeu erro 1101 em todas as rotas desde ~17:00 UTC de 03/11 (I-5102f4e9) M, [incidente] |

**A vazão de hoje** fica entre 0,0028 e 0,0114 PR/s, ou seja, entre 17 % e 68 % do primeiro degrau desta arquitetura
(1/min = 0,0167 PR/s) e perto do degrau 1 da semente (0,0116 PR/s) na melhor hora.

**As restrições, em ordem** (passo 1 de Goldratt, [toc](../research/toc.md)): (1) a oferta de unidades prontas e
independentes, que é exatamente o problema do planejador; (2) a CPU da caixa, com 105 s de gate por PR; (3) o forge,
assim que a vazão passar de ~0,1 PR/s (seção 3); (4) a cota de IA, porque cada PR é escrita inteira por IA.

## 2. Os três limites em cada passo

A semente (§5) mede todo trabalho contra três limites: o individual (o que o motor faz hoje), o estado da arte e o
limite físico. Desperdício é a distância entre eles. Os números do estado da arte vêm de [04](04-componentes.md) e os
físicos de [05](05-orcamento-e-degraus.md).

| Passo | Individual (motor, hoje) | Estado da arte (melhor publicado) | Limite físico |
|---|---|---|---|
| 1. Decidir | ~0,01 decisão/s, A = 1 | o Google faz milhares de mudanças automatizadas por dia pelo Rosie [S3]; migrações com LLM: 595 mudanças em 12 meses, 74 % das edições pela IA [V28]; a Anthropic passou de ~2.500 para mais de 30.000 mudanças mergeadas por dia entre mai e set/2026 (~0,35/s) [A17]; no GitHub, mais de 40 % das PRs já começam por um agente [S17] | a inferência do mundo ([05](05-orcamento-e-degraus.md)) |
| 2. Gerar | ~10^6 tokens e minutos de sessão por PR | uma busca estrutural por AST custa ~86 µs por arquivo (benchmark de fornecedor) [V36]; a Airbnb migrou ~3.500 arquivos de teste em 6 semanas [V34] | ns por edição em memória |
| 3. Verificar | 105 s por PR (mediana), uma suíte por vez na caixa | o TAP do Google roda mais de 4 bilhões de testes por dia sobre mais de 50 mil mudanças por dia [S4]; o CQ do Chromium reaproveita builds verdes por até 800 commits [S13] | µs para conferir um certificado ([05](05-orcamento-e-degraus.md)) |
| 4. Gravar | ~0,01 merge/s pela API do forge | 60 a 70 mil commits por dia útil num repositório só no Google (~0,7–0,8/s) [S2]; FoundationDB: dezenas de milhares de commits/s por cluster com 1,5–2,5 ms de latência [S22] | µs por anexo por núcleo; a rede entre réplicas |
| 5. Coordenar | uma trava de caixa; um Durable Object | Kafka no LinkedIn: mais de 7 × 10^12 mensagens/dia [C7]; Cadence na Uber: ~10^5 atualizações de workflow/s [C29]; o escalonador do Kubernetes: 680–1.100 pods/s [C33] | µs por mensagem por núcleo |

## 3. Os dados da Torre T1 a T3

### T1. "Trem serial, gate de ~10,5 s, teto ~360 PRs/h" — **derrubado no número**

- O trem (fila de merge em lote) está **parado**; as PRs entram por `scripts/deliver`, uma sessão por vez, serializadas
  pela trava da caixa [M, AGENTS.md e sistema §1]. "Serial" vale; "trem" não é o mecanismo de hoje.
- O ciclo medido do head ao merge tem mediana de **105 s**, dez vezes os 10,5 s do dado. O teto da caixa para PRs de
  código é 3.600 s ÷ 105 s ≈ **34 PRs/h** [M, sistema §1]; com PRs só de documento (~50 s de gate,
  [design do trem](../programs/vazao/design-trem.md)) chega a ~72/h [I]. A melhor hora medida teve 41 PRs [M].
- O número 10,5 s aparece no motor como o tempo em processos dos testes do trem na fase F8 do gate-speed
  ([F8](../programs/gate-speed/phases/F8.md)), não como o gate de uma PR. 360 PRs/h exigiriam um ciclo de 10 s, que é a
  meta que Daniel deu ao gate-speed (D-122) e que só o caso de cache cheio atinge (0,99 s); não é a medida em produção.

### T2. "O control plane na Cloudflare estourou a cota diária de leituras" — **plausível pela conta, não confirmado**

- A cota do plano grátis dos Durable Objects é **5.000.000 linhas lidas por dia**, 100.000 linhas escritas e 100.000
  requisições por dia; passada a cota, as operações daquele tipo falham até 00:00 UTC [C2]. Linha lida é **linha
  varrida**, não linha devolvida [C4]. Um Durable Object atende ~1.000 requisições/s [C3].
- O incidente I-5102f4e9 segue aberto com a causa como hipótese: confirmar exige o painel da Cloudflare [M]. A conta
  fecha [I]: cada leitura de configuração varria uma janela de 2.000 registros (`forge-events.git_ref_window`), com
  cache de só 60 s por checkout, e o #82 acrescentou leituras de 8.000 e 32.000 registros. 2.500 leituras de 2.000
  linhas por dia já são 5 milhões; uma leitura de 1.000 linhas a cada 15 s também passa da cota (5,76 milhões/dia).
- A causa estrutural é a que o incidente já classificou: **mecanismo faltando**, nenhum orçamento sobre as leituras que
  o motor faz do próprio control plane, com custo proporcional à janela e não ao que o leitor precisa. A arquitetura
  responde com P9 (orçamento antes da fila) e com leitura por índice ([03](03-arquitetura.md)).

### T3. "API do Origin: 600 / 3.000 / 6.000 pontos/min; merge 10, leitura 1, escrita 5; orçamento de git não documentado" — **confirmado**

- Medido nesta sessão com a chave de usuário: limite de **600** pontos por janela, leitura (GET) custa **1** ponto e
  escrita (um PATCH idempotente no título da própria PR #263) custa **5** [M, cabeçalhos `x-ratelimit-*`].
- A documentação do Origin traz 3.000 pontos/min para o token de instalação e 6.000 para o JWT de app (subiu de 600 em
  19/08/2026); o merge custa 10 pontos, como também criar repositório e consultar se uma PR é mergeável; ler o limite
  não custa nada; acima do orçamento a resposta é HTTP 429 com `Retry-After` [S21, trecho de busca: cursor.com estava
  bloqueado pelo egress desta sessão].
- O git por HTTPS tem orçamento próprio desde 16/09/2026, reportado nos cabeçalhos como recurso `git`, **sem valor
  publicado** [S21, trecho]. O dado vale como estava: o orçamento de git existe e não é documentado em número.

**O teto do forge como registro** [I, com o custo por PR estimado]: uma PR do fluxo de hoje gasta ~20 leituras, ~4
escritas (abrir, check runs, comentário de status), 1 consulta de mergeabilidade e 1 merge, ≈ 60 pontos [E]. Com a regra
da semente de usar no máximo metade de cada limite (RNF-12):

| Credencial | Pontos/min | PRs/min a 100 % | PRs/s a 50 % |
|---|---|---|---|
| usuário | 600 | 10 | 0,08 |
| token de instalação | 3.000 | 50 | 0,42 |
| JWT de app | 6.000 | 100 | 0,83 |

O forge, mesmo com o JWT de app, não sustenta 1 PR/s com folga, e o orçamento de git é desconhecido. O GitHub, para
comparar, recomenda no máximo 6 pushes e 1 PR mergeada por minuto por repositório [S14]; os forges são desenhados para
merges em ritmo humano. Por isso a arquitetura tira o forge do caminho crítico a partir do degrau 1/s (AD-2 em
[03](03-arquitetura.md)).

## 4. O que já está no lugar certo

O motor de hoje já tem, em pequena escala, várias formas que a arquitetura de referência generaliza:

- **Portas e adaptadores** para forge, agente, escada de modelos, runner de CI e armazenamento
  ([PORTS.md](../architecture/PORTS.md)): é P8.
- **Envelope de evento com chave de idempotência** (`event_id` = sha256 de produtor, tipo e chave natural): é o que
  RNF-09 pede.
- **Cache de resultado por conteúdo** no gate (tier 1) e o resultado compartilhado do gate-speed (0,99 s): é o embrião
  do C09 e do V1.
- **Posse exclusiva de unidade por lane** (P-13) e o check de posse: é o embrião dos claims (C24) e da chave de
  partição.
- **Verde no head exato com `--expect-head`** e o novo julgamento quando a base anda: é a validação otimista (P5) com
  uma partição só.
- **Lote no trem** (D-297, desligado por padrão) e a seleção de testes por conteúdo: são AD-3 e AD-4 no primeiro
  degrau.

O que falta é o que a escala exige e o motor ainda não tem: a decisão como unidade de trabalho da IA (A > 1), o
certificado, o ledger fora do forge, as partições e as células.
