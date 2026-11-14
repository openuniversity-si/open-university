# Arquitetura de referência: fábrica de software com IA, de 1 PR/min a 10^9 PRs/s

**Comece por aqui.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), um documento único
sob a fronteira de Daniel; o caminho para implementá-la, em projetos, fases e PRs, com a ordem de merge das PRs abertas,
está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md). Os outros documentos desta pasta ficam como referência e
histórico.

Resumo executivo do projeto ARQ-REF, em cinco entregas. A primeira desenhou a fábrica para 10^9 PRs/s com o estado da
arte de hoje (PR [#263](https://cursor.com/codebase/openuniversity-si/open-university/pull/263)). A segunda recorta,
da mesma arquitetura e com as mesmas portas, o que dá para implantar hoje, dimensionado para **1 PR/min** e crescendo
só em números até 1 PR/s, e acabar com os problemas de gate, merge, fila, Origin, sessões e estado (PR [#264](https://cursor.com/codebase/openuniversity-si/open-university/pull/264),
empilhada na #263). A terceira, o passo zero, revê o modelo do motor a partir da intenção antes de qualquer DDL (PR
[#266](https://cursor.com/codebase/openuniversity-si/open-university/pull/266), empilhada na #264). A quarta separa a
infraestrutura da gestão e da liderança, pela fronteira de Daniel, em três fases (PR
[#267](https://cursor.com/codebase/openuniversity-si/open-university/pull/267), empilhada na #266). A quinta consolida a
fase 1 na arquitetura-alvo e no plano de implementação (PR
[#269](https://cursor.com/codebase/openuniversity-si/open-university/pull/269), empilhada na #267). Recurso pago
aparece sempre como recomendação com custo mensal; nada foi criado.

## Três sistemas, em três fases

Decisão de Daniel (04/11 11:37 e 11:39, a partir de Falconi [N17]: liderança, método de gestão e conhecimento técnico),
com os registros de 11:45 (a fábrica pode rodar na conta de quem a usa ou na nossa, com vários clientes) e de 12:05 a
12:17, e a fronteira que ele aprovou às 12:19: três sistemas, só três, e a infraestrutura conhece só trabalho. Toda a
arquitetura passou por essa fronteira, peça por peça ([22](22-tres-camadas.md)), e a planta foi reorganizada pelos três
sistemas ([18 §4](18-planta-geral.md#4-os-três-sistemas-e-as-conexões)).

| Fase | Sistema | O que é | Estado |
|---|---|---|---|
| **1** | **Infraestrutura** | executa e registra trabalho, sem saber por quê: o trabalho (identificador, entrada opaca, estado), o executor por adaptador (contêiner ou script, sessão de IA, forge; a pessoa como extensão futura, dormente), a saída como o executor a produziu, o registro bruto e o acesso a ele, e as propriedades físicas (isolamento entre tenants, durabilidade, segurança, o mecanismo de limite); mecanismos parametrizáveis cujos valores vêm de fora (filas com política de ordenação, retentativa, dependências, roteamento por seletor e capacidade, retomada de espera, limites com preço por medidor); nada da gestão, nem campo de contexto: 13 tabelas em `work` e `log` ([22 §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura)) | **em implantação**: a #265 (bootstrap, orçamento e rede, com a D-304, a D-305 e a D-306 e o teste que as prova) e as próximas PRs de infraestrutura |
| **2** | **Gestão** | transforma o querer em trabalho definido, com esquema, tabelas e lógica próprios: no nosso caso, objetivo, aposta, planejador, processo, etapas e plano de commits, padrão, que checagens provam uma PR e quando pousar, que executor usar, métricas, painéis e alertas lidos do registro, premissas e aprendizado. Outra gestão pode não ter meta nenhuma | **desenho como insumo, sem implementação**: [17](17-ciclo-do-processo.md), [19](19-direcao-ideal.md), [20](20-sistema-de-aprendizado.md), [21 §4 a §6](21-revisao-geral.md#4-a-medição), o desenho de [11](11-gate-merge-fila-origin.md) como política de integração, as fontes N e L |
| **3** | **Liderança** | o que se quer: a intenção com a trava, a métrica-norte, os limites e a autoridade, o canal com a Torre, as decisões | **desenho como insumo, sem implementação**: [19 §6 e §7](19-direcao-ideal.md#6-a-governança), a [SEMENTE](../SEMENTE.md) |

**O teste de aceite da fase 1:** trocar o sistema de gestão inteiro, ou o comportamento de execução, sem mudar uma linha da
infraestrutura; e o mesmo trabalho rodar como script, sem sessão de IA, e como sessão de IA. As tabelas rodaram assim no
PostgreSQL 18.6: uma gestão com metas nas tabelas dela e outra de trabalhadores autônomos sem tabela nenhuma, o mesmo
trabalho por script e por sessão de IA, uma pessoa como executor no esquema, filas com políticas diferentes, o roteamento, a
retentativa, as dependências, o cache, os limites de parada, de recusa e em dinheiro, um pouso por vez no mesmo ramo e
nenhum nome de gestão, de liderança, de medida ou de tipo de executor no esquema
([22 §6](22-tres-camadas.md#6-o-teste-de-aceite)).

## Passo zero: o modelo do motor revisto a partir da intenção

Pedido de Daniel (04/11 10:44 e 10:46): antes de qualquer DDL na AWS, revisar todo o modelo de negócio do motor a partir
da intenção de origem, "fornecer uma estrutura que possibilite janelas mais longas de autonomia dos agentes", e não do
que existe ([18](18-planta-geral.md) a [21](21-revisao-geral.md)). Uma auditoria do repositório e do log de eventos deu
a evidência, e uma pesquisa de como os melhores fazem, as práticas (grupos B, L e N de [referencias](referencias.md)).

1. **A planta** ([18](18-planta-geral.md)): dez subsistemas em três grupos (rumo, execução, melhoria), mais a
   plataforma; **cada um existe para que uma classe de parada não aconteça**, e a planta inteira se mede pelo tamanho
   das janelas de autonomia. Cada subsistema tem escritor único, comandos, eventos e saúde medida; a planta vira um
   catálogo versionado e testado, para não envelhecer.
2. **A direção** ([19](19-direcao-ideal.md)): quatro níveis com dono e estado, intenção → objetivo → aposta → processo.
   O portfólio e a fase saem como entidades, o programa ganha uma definição só (um objetivo medido) e o projeto vira
   aposta, com efeito esperado e veredito. O planejador é um workflow que registra cada escolha; o padrão vira entidade
   com versão. Do estado da arte: objetivos `committed` ou `aspirational` sobre métricas de entrada, apostas com
   apetite e disjuntor, escolhas pontuadas por valor × viabilidade, orçamentos encaixados da aposta à tentativa.
   **Proposta a Daniel:** a janela de autonomia como métrica-norte, com PRs por segundo como capacidade.
3. **O aprendizado** ([20](20-sistema-de-aprendizado.md)) no lugar da retrospectiva: evidência → sinal → lição →
   hipótese → versão candidata do padrão → experimento → veredito → adoção ou reversão, com o laço duplo para premissas
   e objetivos. Hoje o ciclo está aberto em todos os elos: 16 lições, nenhuma aplicada, nenhum efeito medido. A 1 PR/min, um A/B sobre taxa rara leva semanas; o aprendizado de agora prefere efeitos grandes,
   durações e reexecução de processos passados.
4. **A revisão geral** ([21](21-revisao-geral.md)): toda etapa com início e fim, toda intervenção e todo gasto de sessão
   como evento, toda tentativa com a versão do padrão; o estado de execução fora do git; 66 comandos reduzidos a
   `tower <subsistema> <verbo>`, clientes finos do contrato de cada subsistema; as instruções, com sete regras que o
   código desmente e nove pares que se contradizem, trocadas por pacotes gerados das regras e um teste do padrão; a
   padronização na AWS (nomes, tags com prefixo e ativadas para custo, segredos, logs, identidade), com a estrutura de
   contas para Daniel decidir; e o mesmo desenho de 1 PR/min a 1 PR/s.

## 1 PR/min agora, 1 PR/s depois, implantável hoje

1. **O problema é de forma, não de esforço.** Os 27 incidentes até 03/11 caem em sete classes: dois escritores no mesmo
   branch, credencial do forge nas sessões, estado em git e no plano grátis, sessões que param e ninguém retoma,
   computação do gate fixa e pequena, fornecedor sem a capacidade pedida e merge serial ([09](09-avaliacao-10-0.md)).
2. **A forma recomendada (A1): AWS com PostgreSQL gerenciado (RDS) e workflows e filas em Python (DBOS) no mesmo
   banco**, um runner quente e runners de rajada do gate em contêiner, S3 para logs e cache, e o Origin como forge, com
   o GitHub pela mesma porta. Nenhuma máquina de estimação no caminho crítico: a VM do runner sai, o box do Grok Bot vira
   cliente. **Todos os componentes desde o primeiro dia, dimensionados para 1 PR/min** com os serviços mais baratos da
   AWS (Daniel, 04/11 00:38, 01:06 e 01:08): RDS db.t4g.micro numa zona, uma tarefa de 0,25 vCPU para o orquestrador,
   Fargate Spot, Parameter Store e a franquia grátis do CloudWatch. Para 1 PR/s só crescem números (classe e réplica do
   banco, tarefas, runners, lote, partições); por isso a caixa EC2 fica de fora
   ([10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia), [13](13-estado-e-coordenacao.md)).
3. **Gate, merge e fila definitivos, com entrega em ~1 s.** Um escritor por branch; a prova do head roda no push, no
   runner quente, em paralelo com o tier 1 da sessão, com o veredito guardado por alvo; a PR pronta sai num lote de uma,
   sem janela, e pousa pela API com o head exato. Meta a 1 PR/min: "pronta → mergeada" p50 ≤ 1 s, p99 ≤ 3 s. Fica acima
   de 1 s rodar os testes (10,5 s quente hoje, agora antes da pronta), a prova atrasada, a base que mudou a entrada da
   PR e o forge, cuja latência de merge ainda não foi medida. Sob carga, o mesmo desenho junta em lote o que já espera
   (até 24 PRs; p50 ≤ 5 min a 1 PR/s); ≤ 27 pontos de API por PR, zero recusa de push
   ([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)).
4. **Unidade e sessões no estado da arte.** Contrato da unidade (idempotência, lease, prazos, retentativa, sem pedir
   decisão) executado por workflow durável. **No degrau atual, enquanto o uso é pessoal, interno e não comercial
   (Daniel, 04/11 00:35), os adaptadores principais são os agentes de nuvem das assinaturas que ele já tem** (Claude
   Code, Cursor, Codex); o agente próprio em contêiner com modelos no Bedrock fica pronto como adaptador futuro. Os termos
   da Anthropic dizem que os limites dos planos assumem uso individual comum e que produtos devem usar chave de API ou
   provedor de nuvem; a troca tem quatro gatilhos escritos: o uso deixar de ser pessoal, interno e não comercial, o
   volume passar da cota, um aviso do fornecedor, ou faltar capacidade. A 1 PR/min são ~15 sessões simultâneas, dentro
   do que as assinaturas sustentam ([12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau)).
5. **O modelo de domínio é refinado, não copiado** (Daniel, 04/11 00:43 e 00:44). Ele afeta tabelas, eventos e
   workflows, não os componentes, e é por isso que o banco é relacional. O modelo de hoje falha em dez pontos com
   evidência ("unidade" nomeia quatro coisas, posse e sessão sem registro, o mesmo fato em seis lugares, numeração
   local). O refinado usa os níveis do METODO (portfólio, programa, projeto, fase, processo e operação: o processo é a
   PR, a operação é o evento) e separa tentativa e sessão. Cada agregado tem um escritor só e um id alocado pelo banco.
   O núcleo das tabelas rodou no PostgreSQL 18.6 ([16](16-modelo-de-dominio.md)). Dentro do processo
   ([17](17-ciclo-do-processo.md)), as etapas do METODO viram eventos com artefato e o plano de commits vira um grafo
   com caminho crítico: uma tentativa por processo, o paralelismo entre processos, e a sequência de eventos do primeiro
   push ao merge, cada um com emissor e causa.
6. **O custo novo hoje é só a infraestrutura; depois de um gatilho de troca, ele está nos agentes**
   ([14](14-custos-e-migracao.md)):

| Degrau | Sessões de agente | Infraestrutura e gate (A1, crédito AWS) | Agentes por mês | Total novo por mês |
|---|---|---|---|---|
| **1 PR/min, agora, uso pessoal** | assinaturas (Claude Code, Cursor, Codex) | **~US$ 53** (~US$ 87 com o runner quente sob demanda) | as assinaturas já pagas; a Cursor em nuvem ao preço de API do modelo | **~US$ 53** + o uso da Cursor |
| 1 PR/min, depois de um gatilho, A = 1 | agente próprio com Bedrock | ~US$ 53 | ~US$ 6,4 mil | ~US$ 6,5 mil |
| 0,1 PR/s, depois de um gatilho, A = 1 | idem | ~US$ 131–235 | ~US$ 39–42 mil | ~US$ 39–42 mil |
| 1 PR/s, A = 10 | idem | ~US$ 552–1.495 | ~US$ 39–42 mil | ~US$ 39–43 mil |
| 1 PR/s, A = 1 | idem | ~US$ 552–1.495 | ~US$ 386–417 mil | ~US$ 390–420 mil |

   O crédito AWS de hoje, **US$ 1.100** (US$ 1.000 do Activate até 10/2028, US$ 100 da camada gratuita até 10/2027),
   paga a **A1 a 1 PR/min** (~US$ 53/mês) por **~21 meses**, até ~jul/2028; a 0,1 PR/s, por 5 a 8 meses; a 1 PR/s, por
   3 semanas a 2 meses; agentes por API, só alguns dias. Depois dele, o mesmo valor sai do bolso
   ([14 §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura)).
7. **Amanhã, sem dinheiro:** um escritor por branch; filtro e lote na caixa de hoje (de ~41 para ~150–190 PRs/h
   estimados); medir o Origin (merges por minuto, orçamento de git, pouso por pilha); o contrato da unidade na fila.
   **Decididas por Daniel** (04/11 01:39): A1 a 1 PR/min, o runner quente sempre ligado e o teto de US$ 60/mês no AWS
   Budgets, que a Torre já criou; para valer sobre o crédito, ele precisa excluir créditos e reembolsos. O orçamento de
   agentes fica para quando um gatilho disparar.

## 10^9 PRs/s, a referência de longo prazo

1. **10^9 só fecha se a IA decidir no atacado e programas aplicarem no varejo:** amplificação A ≥ 10^6 (no máximo 0,15
   token de IA por PR mergeada; o motor gasta ~10^6 hoje). Com IA PR a PR, o hardware de inferência do mundo inteiro faz
   ~7 × 10^4 PRs/s.
2. **A forma é um motor de derivação em dois níveis:** por decisão, planejar, escrever a transformação e certificá-la; por
   instância, aplicar, conferir o certificado em 1 µs e anexar a um ledger particionado, em células independentes.
3. **O gate de microssegundos é possível como conferência** (~1,3 × 10^3 núcleos a 10^9), não como compilação e teste: a
   verificação cara vai para a decisão.
4. **O resto é infraestrutura e dinheiro:** ~US$ 0,5–2 bilhões por ano a 10^9 (1,7–6 × 10^-8 dólar por PR).
5. **É pesquisa, só da Torre:** o planejador com A ≥ 10^6, a certificação barata de transformações, o que testar depois
   do merge a 10^9 mudanças por segundo, a independência semântica e onde existe trabalho útil para 10^9 PRs/s.

## Os documentos

**1 PR/min a 1 PR/s:** [09 avaliação](09-avaliacao-10-0.md) · [10 arquitetura](10-arquitetura-10-0.md) ·
[11 gate, merge, fila e Origin](11-gate-merge-fila-origin.md) · [12 unidade e sessões](12-unidade-e-sessoes.md) ·
[13 estado](13-estado-e-coordenacao.md) · [14 custos e migração](14-custos-e-migracao.md) ·
[15 verificação](15-verificacao-10-0.md) · [16 modelo de domínio](16-modelo-de-dominio.md) ·
[17 ciclo do processo](17-ciclo-do-processo.md)

**Passo zero:** [18 planta geral](18-planta-geral.md) · [19 direção ideal](19-direcao-ideal.md) ·
[20 sistema de aprendizado](20-sistema-de-aprendizado.md) · [21 revisão geral](21-revisao-geral.md)

**Três camadas:** [22 as três camadas e o núcleo técnico agnóstico](22-tres-camadas.md)

**10^9:** [00 avaliação](00-avaliacao.md) · [01 requisitos](01-requisitos.md) · [02 estado atual](02-estado-atual.md) ·
[03 arquitetura](03-arquitetura.md) · [04 componentes](04-componentes.md) · [05 orçamento e degraus](05-orcamento-e-degraus.md) ·
[06 contrato do planejador](06-contrato-planejador.md) · [07 lacunas](07-lacunas.md) · [08 verificação](08-verificacao.md)

[Referências](referencias.md): cada fonte diz se foi lida na página ou vista só no trecho da busca, porque o egress
desta sessão bloqueia a maior parte dos sites primários.
