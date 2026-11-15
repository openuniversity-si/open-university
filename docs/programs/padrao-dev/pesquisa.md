# PADRAO-DEV — pesquisa

Como os melhores fazem, no estado da arte humano e no desenvolvimento por agentes em escala, e o que serve para nós
(método §5: o estado da arte é o piso). Levantamento de 15/11/2026. A rede desta sessão abriu poucas páginas: cada
referência é marcada `[lida]` (página lida), `[busca]` (título e resumo confirmados por busca) ou `[memória]` (canônica,
não confirmada aqui). Os números vêm dos resumos.

## Quem faz melhor

**1. Normas: o que gerir, nunca como.** O [SWEBOK v4](https://www.computer.org/education/bodies-of-knowledge/software-engineering)
`[busca]` (IEEE, 2024) lista 18 áreas de conhecimento (requisitos, arquitetura, projeto, construção, teste, operação,
manutenção, configuração, qualidade, segurança, processo, entre outras). A ISO/IEC/IEEE 12207 `[memória]` define os
processos do ciclo de vida e permite adaptá-los a um subconjunto; a 29148 `[busca]` dá os atributos de um requisito
(identificador, fundamento, **método de verificação**, rastreabilidade); a 42010 `[memória]` trata a arquitetura como
preocupações, visões e *regras de correspondência*; a 25010 `[memória]` é o modelo de qualidade. Nenhuma fala de agentes
nem de 1 PR por minuto.

**2. Requisitos como dado, com rastreio gerado.** Em sistemas críticos (DO-178C, ISO 26262,
[LDRA](https://ldra.com/ldra-blog/do-178c-structural-coverage-analysis/) `[busca]`) cada requisito liga a testes e cada
teste a um requisito, e código coberto que nenhum requisito justifica é sinal de requisito faltante. As ferramentas
"como código" ([Doorstop](https://github.com/doorstop-dev/doorstop) `[memória]`, OpenFastTrace `[memória]`,
[Sphinx-Needs](https://x-as-code.useblocks.com/how-to-guides/trace-code/index.html) `[busca]`,
[StrictDoc](https://strictdoc.readthedocs.io/en/latest/strictdoc_02_faq.html) `[busca]`) guardam **um arquivo por
requisito**, a ligação é declarada no próprio teste e um rastreador falha o build com requisito sem teste ou teste sem
requisito. Para agentes, a "especificação primeiro" (Spec Kit, Kiro; [Fowler/Böckeler](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)
`[busca]`) não tem evidência de ganho: o único estudo rigoroso encontrado
([Hill, ESEM 2026](https://drops.dagstuhl.de/storage/00lipics/lipics-vol394-esem2026/LIPIcs.ESEM.2026.84/LIPIcs.ESEM.2026.84.pdf)
`[busca]`) não achou redução de defeitos.

**3. Arquitetura: regras como testes, decisões imutáveis.** Arquitetura evolutiva é mudança guiada por **funções de
aptidão**, checagens automáticas de cada característica no pipeline ([Ford, Parsons, Kua](https://nealford.com/books/buildingevolutionaryarchitectures.html)
`[busca]`). As decisões são registros imutáveis, um por arquivo, substituídos em vez de editados (Nygard, [MADR](https://adr.github.io/madr/)
`[memória]`, que pede uma seção de *confirmação*: como verificar a decisão). As dependências são regras executáveis:
[Bazel visibility](https://bazel.build/concepts/visibility) `[busca]` falha o build com um dependente não autorizado;
[ArchUnit](https://archunit.org/) `[busca]` e import-linter `[memória]` fazem camadas e ciclos virarem teste. O Google
guarda a declaração de dependência no BUILD do próprio pacote, local ao dono ([Potvin e Levenberg, CACM 2016](https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)
`[busca]`).

**4. Modularidade: o que a evidência diz.** Decompor por *decisões que podem mudar* ([Parnas 1972](https://dl.acm.org/doi/10.1145/361598.361623)
`[busca]`). Contribuições não modulares conflitam significativamente mais, em 73.504 cenários de merge
([Dias, Borba, Barreto, IST 2020](https://merge-conflict-factors.github.io/merge-conflict-factors) `[busca]`); muitas
mãos no mesmo artefato preveem defeitos melhor que churn e cobertura ([Nagappan et al., ICSE 2008](https://www.microsoft.com/en-us/research/?p=153188)
`[busca]`). Mas o acoplamento real forma um núcleo que atravessa os diretórios em 70–80 % dos sistemas
([Baldwin, MacCormack, Rusnak 2014](https://dash.harvard.edu/bitstream/handle/1/10646422/baldwin%2cmaccormack%2crusnak_hidden-structure.pdf?sequence=3)
`[busca]`), o acoplamento por co-mudança aparece no histórico e não no código ([Zimmermann et al., ICSE 2004](https://www.st.uni-trier.de/diehl/pubs/icse04.pdf)
`[busca]`), e agentes produzem modularidade superficial, separada em arquivos sem coesão
([Modular Mirage, arXiv 2605.02741](https://arxiv.org/html/2605.02741v1) `[busca]`).

**5. Arquivos compartilhados.** Changelogs convergiram para um fragmento por mudança e o agregado gerado
([towncrier](https://towncrier.readthedocs.io/en/trunk/release-notes.html), [reno](https://docs.openstack.org/reno/latest/index.html)
`[busca]`; changesets `[memória]`); o reno deriva até a pertença a uma versão do histórico do git. Conflitos não são só
textuais: muitos aparecem como build ou teste vermelho depois de um merge limpo ([Brun et al., ESEC/FSE 2011](https://homes.cs.washington.edu/~mernst/pubs/vc-conflicts-fse2011.pdf)
`[busca]`), e esses só uma fila que testa a combinação pega ([Uber SubmitQueue, EuroSys 2019](https://www.uber.com/blog/research/keeping-master-green-at-scale)
`[busca]`: antes dela o `main` do iOS ficava verde cerca de 52 % do tempo).

**6. Testes: contabilidade, mapa derivado, adequação medida.** A seleção de testes do Google (TAP) vem do grafo de
dependências do build ([Memon et al., ICSE-SEIP 2017](https://research.google/pubs/taming-google-scale-continuous-testing/)
`[busca]`); a da Meta, de um modelo que corta o custo pela metade mantendo 99,9 % das mudanças defeituosas detectadas
([Machalica et al., 2019](https://arxiv.org/abs/1810.05286) `[busca]`); nenhuma de anotação humana. A cobertura útil é a
das linhas alteradas, mostrada na mudança ([Ivanković et al., FSE 2019](https://homes.cs.washington.edu/~rjust/publ/google_coverage_fse_2019.pdf)
`[busca]`), e não é meta: correlaciona pouco com a eficácia ([Inozemtseva e Holmes, ICSE 2014](https://cs.ubc.ca/~rtholmes/papers/icse_2014_inozemtseva.pdf)
`[busca]`). O que mede se um teste verifica algo é mutação, viável em escala quando restrita ao diff
([Petrović et al., Google, TSE 2021](https://research.google/pubs/practical-mutation-testing-at-scale-a-view-from-google/)
`[busca]`; [Meta ACH, FSE 2025](https://arxiv.org/abs/2501.12862) `[busca]`). "O teste rodou?" se resolve por
contabilidade: o plano `1..N` do [TAP 14](https://testanything.org/tap-version-14-specification.html) `[busca]` ou um
inventário esperado comparado com o executado. Instabilidade tem sistema próprio: 1,5 % das execuções do Google são
instáveis, e os testes que seguem falhando saem do gate para uma suíte de confiabilidade
([Micco 2016](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html) `[busca]`).

**7. Entrega em volume.** As métricas da [DORA](https://dora.dev/guides/dora-metrics/) `[busca]` são cinco, em dois
fatores; a quinta, de 2024, é a **taxa de retrabalho** do deploy. A [DORA 2025](https://services.google.com/fh/files/misc/2025_state_of_ai_assisted_software_development.pdf)
`[busca]` conclui que a IA é um amplificador: ela correlaciona com mais vazão e também com mais instabilidade, e lotes
pequenos e uma plataforma interna de qualidade estão entre as capacidades que separam os bons. Com fila serial e 60 s de
checagem, o teto é cerca de 1 merge por minuto: o [Uber](https://arxiv.org/abs/2501.03440v1) `[busca]`, a
[Shopify](https://shopify.engineering/successfully-merging-work-1000-developers) `[busca]` e a
[fila do GitHub](https://docs.github.com/en/enterprise-server@3.19/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
`[busca]` passam disso com grupos especulativos, e a taxa de ejeção da fila domina a vazão.

**8. Agentes em escala (2025–2026): restrição mecânica vence prosa.** A OpenAI escreveu um produto de cerca de um
milhão de linhas sem código humano e aplica a arquitetura por linters e testes estruturais com mensagens escritas para o
agente; o AGENTS.md é um mapa curto ([Harness engineering](https://openai.com/index/harness-engineering/) `[busca]`,
[InfoQ](https://www.infoq.com/news/2026/02/openai-harness-engineering-codex) `[busca]`). A Anthropic separa instrução
não determinística (CLAUDE.md, sem garantia) de determinística (hooks e configuração, que o harness executa): uma regra
que o agente segue errando vai para um hook ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)
`[lida]`; [harnesses para agentes longos](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
`[lida]`, com estado em JSON e não em prosa). A Stripe produz mais de 1.300 PRs por semana com agentes, lint local abaixo
de 5 s e no máximo duas rodadas de CI ([Minions](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
`[busca]`); o Spotify, com verificadores determinísticos antes da PR ([Honk](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
`[busca]`). Arquivos de contexto como o AGENTS.md quase não aumentam o sucesso e custam mais de 20 % a mais
([Gloaguen et al., ICLR 2026](https://arxiv.org/html/2602.11988) `[busca]`); a qualidade cai com o tamanho do contexto
([context rot](https://research.trychroma.com/context-rot) `[memória]`) e com o tamanho da tarefa
([METR](https://arxiv.org/html/2503.14499v3) `[busca]`); sem guardas, o código de agentes acumula +30 % de avisos
estáticos e +41 % de complexidade, que anulam o ganho de velocidade em dois meses
([He, Kästner, Vasilescu et al., MSR 2026](https://arxiv.org/abs/2511.04427) `[busca]`). A prontidão de um repositório
para agentes é medida por pilares automáticos: lint, formatador, verificação de tipos, testes rápidos, instabilidade
corrigida ([Factory Agent Readiness](https://docs.factory.ai/agent-readiness/overview) `[busca]`).

**9. Gerir o próprio padrão.** O Google aplica as regras por ferramenta sempre que possível e deixa em prosa só o que
exige julgamento; um aviso que o desenvolvedor não age em mais de 10 % dos casos mata a ferramenta, e uma regra começa
como aviso e só vira erro depois de limpar o legado ([Sadowski et al., CACM 2018](https://research.google/pubs/lessons-from-building-static-analysis-tools-at-google/)
`[busca]`). Mudanças do padrão seguem um processo de proposta com um arquivo por proposta, estado legível por máquina e
substituição em vez de edição (Rust RFC, PEP 1 `[memória]`). Política como código ([Conftest/OPA](https://www.conftest.dev/),
[Semgrep](https://semgrep.dev/docs/writing-rules/overview) `[memória]`) traz casos de teste por regra: uma checagem sem
teste é um gate não verificado. A conformidade é calculada, nunca preenchida à mão ([Spotify Soundcheck](https://backstage.spotify.com/blog/how-soundcheck-improves-tech-health-pt-1)
`[busca]`, [OpenSSF Scorecard](https://github.com/ossf/scorecard) `[memória]`).

## Encaixe em nós

**As hipóteses do pedido.**
- **(a) Código ultrassegmentado: confirmada na forma certa, não na literal.** A evidência apoia ocultação de
  informação, fronteiras verificadas e mudanças pequenas com pouco contexto (Parnas, Dias, Nagappan, context rot, METR).
  Não apoia "muitos arquivos pequenos": o acoplamento real atravessa diretórios e agentes já tendem à segmentação
  superficial. Nenhum estudo isola a modularidade do repositório como causa do sucesso do agente; medimos aqui, cruzando
  escape e retrabalho com unidades tocadas por PR e com a co-mudança do histórico.
- **(b) Eliminar arquivos compartilhados editados à mão: confirmada, necessária e não suficiente.** Um arquivo por
  entrada, agregado gerado e não editado, unicidade e schema checados, e a fila testando a combinação para os conflitos
  semânticos. Um agregado gerado *versionado* volta a ser compartilhado; o nosso driver de merge regenera só em merge
  local, e a fila do GitHub não o executa.

**Copiar.**
- **Toda regra é dado com checagem, ou é rotulada julgamento** (Google, OpenAI, Anthropic, Soundcheck): catálogo de
  regras com id, fundamento, dono, checagem, modo (aviso ou bloqueio) e testes da própria checagem; o caminho é aviso →
  medir falsos positivos → bloqueio. Já temos o esqueleto (`config/registry/rules.json`, `scripts/rule`) e os
  princípios com "Enforced by" (D-069): falta torná-los o padrão vivo.
- **Mapa teste → código derivado da execução**, não declarado (TAP, Meta). O `covers` escrito à mão vira, no máximo,
  uma declaração checada contra o medido.
- **Contabilidade de testes**: o gate prova quantos testes de cada arquivo rodaram e falha com zero ou com menos que o
  esperado.
- **Adequação medida e com catraca**: cobertura das linhas alteradas por PR e mutação no diff, fora do caminho de 60 s;
  nunca cobertura global como meta.
- **Requisitos como dado, um arquivo cada, com método de verificação**, e a ligação declarada no teste; o rastreador é
  gerado. Nossas decisões (`docs/domain/decisions/`, já um arquivo por decisão) são o ponto de partida.
- **Funções de aptidão de arquitetura** para as regras de forma (portas, unidades, camadas, tamanho), e o grafo de
  dependências gerado; os testes de regra estrutural que já temos (`vendor-ports`, literais) são exatamente isso.
- **Catracas de qualidade estrutural** (lint, tipos, complexidade) para não repetir o achado do Cursor.
- **Taxa de retrabalho** (DORA) como métrica de instabilidade ao lado da vazão.

**Adaptar.**
- Mutação e cobertura total custam minutos: vão para depois do merge e para a noite, com resultado como evento e
  catraca; o gate de 60 s só lê o mapa derivado.
- Fila especulativa: a do GitHub já agrupa; a taxa de ejeção e a de instabilidade entram no painel.

**Não serve (cerimônia para uma organização operada por máquina).** Documentos de plano e relatório de teste da 29119-3,
declarações formais de conformidade, matrizes de rastreio mantidas à mão, aprovações humanas por fase, especificações
longas em prosa antes do código, cobertura global como número-alvo, e prosa normativa sem checagem (ela custa tokens e
não muda o comportamento de forma confiável).
