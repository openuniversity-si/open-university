# A caixa de verificação: Origin, verificação distribuída, computação gratuita e lotes

Pesquisa independente, 2026-11-03. Legenda: **[E]** evidência direta (comando executado, código ou decisão do repositório, documento oficial lido), **[S]** fonte secundária (resumo de busca, blog, documentação vista só por trecho), **[I]** inferência minha.

Limite de rede desta sessão: o proxy de saída recusou (HTTP 403) `cursor.com`, `learncursor.dev`, `developers.cloudflare.com`, `docs.oracle.com` e `cloud.google.com` (depois do redirecionamento). Essas páginas aparecem só pelos trechos da busca (WebSearch), por isso valem como [S] mesmo quando o domínio é oficial. Para lê-las por inteiro, esses hosts precisam ser liberados nas configurações de rede da sessão.

## 1) Resumo

1. O Origin tem o conceito de "job de Origin CI" (`origin pr checks --log`), mas não há documentação pública de runners próprios nem de cota gratuita. Hoje os checks vêm de apps que gravam *check runs* pela API **[E/S]**. O repositório `the-tower` no Origin não tem check nem ruleset, e `origin pr requirements 109` responde "Gates: none required" **[E]**.
2. O Origin pode exigir gates no merge (rulesets `merge_branch`, `pr requirements`) e o merge aceita `--match-head-commit`. A prova pode então ser um check run no head exato, legível por qualquer lane **[E]**.
3. Cada contêiner de lane pode verificar PRs de **outra** lane (sorteada pelo plano de controle), nunca os próprios. O veredito vira um check run assinado pelo app no head exato. Assim a prova é externa ao autor, que é o que SEMENTE §6 exige **[I]**.
4. Sistemas reais resolvem isso com escritores confiáveis e leitores sem escrita (cache remoto do Bazel), proveniência assinada por chave que o tenant não alcança (SLSA L3) e limiar de reconstrutores independentes (in-toto/rebuilderd) **[S]**.
5. Computação grátis que cabe na regra da metade: só o Oracle A1 serve como segunda caixa real, e mesmo assim só ~1 OCPU/6 GB depois do corte de 2026, com cartão, risco de recuperação por ociosidade e de falta de capacidade **[S/I]**. A e2-micro já se mediu 12× mais lenta **[E]**. Cloudflare Containers é pago, e fly.io e Render não servem **[S]**.
6. Lotes numa caixa só, com p = 0,13 e 100 s por gate: o ótimo é k = 4–5 com bisseção que infere a metade vermelha. Isso dá ~0,59 execução por PR, ~60 PRs/h processadas e ~52 verdes/h, acima da meta de 42 **[I, conta na §5]**.
7. Se a lane rodar o gate antes de pedir a caixa (filtro, não prova), o p na caixa cai para ~0,02. Com k = 12 a caixa chega a ~190 PRs/h (~4.600/dia), e com p = 0,01 e k = 24, a ~8.000/dia **[I]**.
8. 10.000/dia (417/h) pede mais que uma caixa: verificação cruzada nas lanes mais cache por conteúdo **atestado** no tier 2, que é exatamente a condição que P-43 deixou em aberto **[E/I]**.

## 2) Origin e CI

**O que o binário diz [E].** `origin agent prompt ci` (origin 2026.10.28) diz: "Read CI checks, their logs, and their exit codes … `--log <job>` prints the full log of one finished **Origin CI job** … Checks from other systems link to their own pages through `detailsUrl`". `origin pr checks` sai com 0 (tudo passou), 1 (falhou ou não há checks) e 8 (pendente). Os campos JSON são `name, headSha, status, conclusion, summary, output, detailsUrl, startedAt, completedAt, group`. Há duas origens de check: jobs do "Origin CI" e sistemas externos.

**Como um check é produzido [E].** A pesquisa da unidade `engine-forge-origin` registra que o status de commit do GitHub equivale, no Origin, a um *check run*: `POST /v1/origin/repos/{owner}/{repo}/check-runs` com token de instalação de app (`oit_`, ≤ 15 min, escopo `repository:checks:write`), emitido a partir de uma chave Ed25519 do app (`docs/units/engine-forge-origin/research.md`). O CLI tem `origin app key add <appId> <keyFile>` para chaves Ed25519 SPKI. A página oficial da API (cursor.com/docs/api/origin) confirma, pelo trecho da busca, check suites e check runs com esse escopo **[S]**.

**Runners do Origin [S, conflitante].** Não encontrei preço nem cota gratuita do "Origin CI". O learncursor.dev diz que o Origin não publicou workflows nem runners próprios. Cellcog diz que o CI vem de parceiros (Depot e Buildkite rodando workflows de Actions; CircleCI tem integração cobrada por uso; StarSling está em early access com preço por uso). Todos são CI de terceiros e ficam excluídos pela regra do motor (ADR-24, D-086, D-087) **[E para a regra]**.

**Estado atual no repositório [E].** `origin repo list` mostra `openuniversity-si/open-university` com `mirrorStatus: no-mirror` (o Origin é o dono). Os PRs 95, 100, 105, 108 e 109 têm `[]` em checks, `origin ruleset list` responde "No rulesets configured", e `origin pr requirements 109` responde "Gates: none required". Hoje nada no forge impede um merge sem prova.

**Consequência [I].** O Origin não dá CPU de graça. Ele dá um **registro externo** (o check run no `headSha`) e um **cadeado de merge** (ruleset exigindo esse check mais `--match-head-commit`). É isso que a verificação distribuída precisa. A CPU tem de vir de outro lugar.

## 3) Verificação distribuída nos contêineres das lanes (com prova externa)

**O problema.** Um contêiner de lane tem CPUs próprias (este tem 4 vCPUs Xeon 2,8 GHz **[E]**), mas julgar o próprio PR é autoavaliação. Ela não conta como prova (SEMENTE §6), e a prova tem de ser externa. O motor já tem as peças de conteúdo: `gate_test_cache` (chave = digest das entradas do teste mais toolchain), `shared_results` (PASS por chave num ref git) e `gate_attested.exact_proof` (prova v4 com o mesmo head, a mesma ponta da base, a mesma toolchain e a mesma versão do gate, lida dos eventos do forge e nunca de marcador local) **[E]**. O que falta é **quem** assina e **por que** confiar. P-43 diz isso: o tier 2 só reusa prova "attested", e "até a atestação existir" não há reuso **[E]**.

**Como sistemas reais fazem [S].**
- *Cache remoto do Bazel:* o Bazel confia que não há registro malicioso no cache. Quem reproduz o hash das entradas pode envenenar o resultado. A prática é **só a CI (ou workers de execução remota) escrever** e os desenvolvedores só lerem (`--remote_upload_local_results=false` mais ACL no servidor). A Stripe chegou a execução remota porque "only trusted workers upload action results".
- *SLSA v1.x:* L2 é proveniência assinada por plataforma hospedada (contra adulteração depois do build). L3 é proveniência assinada por chave **inacessível ao passo de build** (contra adulteração durante o build).
- *Reproducible builds e in-toto:* reconstrutores independentes refazem o artefato, e o cliente aceita quando um **limiar** deles concorda (layout in-toto com `threshold`; rebuilderd no Arch).
- *Uber SubmitQueue:* mantém o master sempre verde executando especulativamente e só aterrissando o que passou no estado exato.

**Desenho proposto [I].**
1. **Separar autor e verificador.** O plano de controle (Cloudflare Worker no plano gratuito, já escolhido em D-086) recebe `pr.opened`/head novo e **sorteia** uma lane verificadora diferente da autora, de preferência de outro provedor (Claude ↔ Cursor ↔ Codex). O autor não escolhe quem o julga.
2. **Julgar o head exato.** A lane verificadora roda `scripts/gate-dev --pr <n>` no próprio contêiner e produz um *statement* no estilo in-toto. O sujeito é `{head, tree, base_tip}`. O predicado é `{gate_version, toolchain_id, chaves e vereditos por teste, digest do log, assignment_id, verificador}`.
3. **Assinar com chave fora da lane.** A chave do app Origin fica só no Worker. Ele posta o check run `gate/<verificador>` no `headSha` **só** para uma atribuição que ele mesmo emitiu e para o verificador sorteado. Nenhuma lane tem a chave, então nenhuma lane forja o check. Isso é o análogo de SLSA L3 para a assinatura, mas não para a execução.
4. **Merge travado no forge.** Um ruleset `merge_branch` exige o check, e o trem usa `--match-head-commit`. Qualquer lane verifica a prova com `origin pr checks <n> --json headSha,conclusion,detailsUrl`.
5. **Auditoria externa da execução.** O contêiner verificador continua sendo de uma sessão de IA, então não é um builder endurecido. Mitigações:
   - a caixa reexecuta uma amostra aleatória (por exemplo 10%) e sempre os PRs que mudam o gate (`scripts/gate-*`) ou de raio alto;
   - para esses, duas verificadoras independentes devem concordar (limiar 2-de-2, como os reconstrutores);
   - como o resultado é função do conteúdo, discordância é flake ou mentira, e as duas abrem incidente com causa raiz (D-081);
   - uma lane pega divergindo perde a credencial de verificadora.
6. **Cache atestado.** Com os PASS por teste assinados por verificadores sorteados, a condição de P-43 se cumpre. O tier 2 (lote do trem) pode reusar um PASS cuja chave bate com as entradas daquele teste **na árvore mesclada** e rodar só os testes cujas chaves mudaram por interação entre PRs. É o modelo do Bazel (escritores confiáveis, leitores sem escrita). Pede uma decisão D-xxx nova, porque altera D-065 (5) e P-43.

**Riscos [I].** Conluio é improvável, porque o sorteio e os provedores diferentes tornam a fraude coordenada cara e porque o modelo de ameaça é sobretudo erro, não malícia. Há também uma pegada de requisições: o Worker grátis tem 100 mil requisições por dia e 10 ms de CPU por invocação **[S]**. A 10 mil PRs/dia, ficar abaixo da metade (50 mil) obriga a ≤ 4–5 requisições por PR. Se as atestações forem para o R2, o teto de D-073 (metade de 1 M escritas Classe A por mês ≈ 16 mil/dia) também limita, e é melhor guardá-las como check run ou ref git. Os limites de taxa da API do Origin não foram encontrados (não verificados).

## 4) Computação gratuita (segunda caixa)

| Serviço | Limite gratuito (2026) | Metade (regra §4) | Python + git + PostgreSQL? | Veredito | Fonte |
|---|---|---|---|---|---|
| Oracle Always Free, Ampere A1 | Cortado em 2026: 1.500 OCPU-h e 9.000 GB-h por mês (≈ 2 OCPU/12 GB contínuos). Antes 3.000/18.000 (4/24). A página oficial em cache ainda mostra o valor antigo. Recupera VM ociosa (limiares divergentes, ~15–20% de CPU). Pede cartão; capacidade escassa. | ≈ 1 OCPU/6 GB | Sim (VM Linux arm64; o manifesto já tem checksums arm64 **[E]**) | Única segunda caixa viável: ≈ ¼–⅓ da caixa **[I]**, risco operacional alto | [S] linuxiac, InfoQ 2026-07, docs.oracle.com |
| Google Cloud e2-micro | 1 instância-mês (≈ 744 h) só em us-west1, us-central1 e us-east1; 30 GB de HDD padrão; 1 GB de rede; 2 vCPU com rajada e 1 GB de RAM | ½ da instância | Sim, mas medida **12,3× mais lenta** que o contêiner, e o gate estourou o timeout de 1.200 s (D-119, D-149) **[E]** | Só fallback; ≈ 3 PRs/h **[I]** | [S] cloud.google.com, guias 2026; [E] DECISIONS |
| Cloudflare Workers (grátis) | 100 mil requisições/dia; 10 ms de CPU por invocação; DO SQLite 100 mil req/dia, 5 GB | 50 mil req/dia | Não (isolate JS, sem processo) | Plano de controle, não caixa | [S] developers.cloudflare.com |
| Cloudflare Containers | Exige Workers Paid (US$ 5/mês); coluna Free = N/A; até 4 vCPU/12 GiB | — | Sim, mas pago | Excluído (pago) | [S] developers.cloudflare.com/containers/pricing |
| fly.io | Organização nova: só teste (≈ 2 h de máquina ou 7 dias); a franquia gratuita antiga só vale para organizações legadas | — | — | Excluído | [S] fly.io/docs/about/discontinued-plans, fórum fly |
| Render | 750 h de instância por mês; dorme após 15 min sem tráfego; Postgres grátis expira em 30 dias, 1 GB | — | Fraco (0,1 CPU, 512 MB) | Excluído | [S] render.com/docs/free |
| Hugging Face Spaces | CPU Basic com 2 vCPU/16 GB e 50 GB efêmeros; dorme sem uso. A documentação indica que Spaces de computação (Docker) exigem plano pago | — | Talvez; uso como CI provavelmente fora do propósito | Excluído (pago/termos) | [S] huggingface.co/docs/hub/spaces-overview |
| Origin CI | Sem runners ou cota públicos | — | — | Desconhecido; reavaliar se o Cursor publicar | [S] learncursor.dev, cellcog |
| Contêineres das lanes | Já existem (uma sessão por lane, CPUs próprias); custo marginal zero | Cabe na regra | Sim (mesma toolchain, mesmo `setup.sh`) **[E]** | **Melhor fonte de CPU** | [E] AGENTS.md, este contêiner |

**Leitura [I].** Nenhum plano gratuito traz CPU comparável à caixa dentro da regra da metade, exceto, em parte, o Oracle A1. O lugar onde a CPU já existe, de graça e escalando com o número de lanes, são os próprios contêineres das sessões. A arquitetura certa é mover a verificação para lá, com prova externa (§3), e não comprar outra caixa.

## 5) Lotes numa caixa (conta)

**Modelo [I].** Uma execução de gate custa T = 100 s, independente do tamanho do lote: a seleção de um lote fica limitada pela suíte completa, ~96 s a frio (D-121) **[E]**. Cada PR é vermelho de forma independente com p. Sem lote a caixa faz 3.600/100 = **36 PRs/h**. Com lote de k, se o lote falha ele é bissectado. Na bisseção "ingênua" as duas metades são testadas. Na "inteligente", se a metade esquerda passa a direita é sabidamente vermelha, então não é retestada e é dividida direto (e um único PR que sobra é ejetado sem rodar). O valor esperado foi calculado por enumeração exata de todos os padrões de falha (k ≤ 12) e por Monte Carlo com 40 mil lotes (k > 12). Os números abaixo são execuções por PR, PRs processadas por hora (= 36 / execuções por PR) e verdes por hora (= processadas × (1−p)).

**p = 0,13 (o vermelho atual entrando direto na caixa):**

| k | P(lote verde) | ingênua: exec/PR | ingênua: PR/h | inteligente: exec/PR | inteligente: PR/h | inteligente: verdes/h |
|---|---|---|---|---|---|---|
| 1 | 0,870 | 1,000 | 36,0 | 1,000 | 36,0 | 31,3 |
| 2 | 0,757 | 0,743 | 48,4 | 0,687 | 52,4 | 45,6 |
| 3 | 0,659 | 0,723 | 49,8 | 0,615 | 58,5 | 50,9 |
| **4** | 0,573 | **0,707** | **50,9** | 0,604 | 59,6 | 51,8 |
| **5** | 0,498 | 0,732 | 49,2 | **0,592** | **60,8** | **52,9** |
| 8 | 0,328 | 0,750 | 48,0 | 0,616 | 58,4 | 50,8 |
| 12 | 0,188 | 0,797 | 45,2 | 0,631 | 57,0 | 49,6 |

Dorfman em dois estágios (lote; se falhar, um por um) tem ótimo em k = 3 com 0,675 exec/PR, ou 53 PRs/h. **Ótimo: k = 5 com bisseção inteligente, +69% sobre k = 1, ~52 PRs verdes/h ≈ 1.270 por dia.** Isso atende a primeira meta (42/h) com ~25% de folga. A curva é rasa entre k = 3 e 8, então um k dinâmico pela taxa observada (mín. 2, máx. 8) é robusto. A latência piora: um lote vermelho de 5 leva até ~6 execuções seriais (~10 min).

**p baixo (a lane roda o gate antes, como filtro; na caixa sobram interações, flakes e erros) [I]:**

| p | k ótimo (inteligente) | exec/PR | PR/h | PR/dia |
|---|---|---|---|---|
| 0,05 | 11 | 0,323 | 111 | ~2.670 |
| 0,02 | 12 / 24 | 0,186 / 0,169 | 194 / 212 | ~4.660 / ~5.100 |
| 0,01 | 24 / 32 | 0,108 / 0,103 | 333 / 349 | ~8.000 / ~8.400 |

**Ressalvas [I].**
- Falhas correlacionadas (dois PRs que quebram juntos) e testes intermitentes inflam o p efetivo e confundem a bisseção. Um flake num lote grande ejeta inocentes, por isso a quarentena de flakes é pré-requisito.
- Se T crescer com k (seleção maior), o ganho encolhe. Se T cair com cache atestado (§3, item 6), o ganho cresce.
- Os números de fornecedores batem com a ordem de grandeza: a Trunk fala em 3–5× com lotes e a Mergify recomenda lotes de 2–3 com mais de 5% de falha e de 5–10 com menos de 2% **[S]**.
- **10.000/dia não cabe numa caixa** nem com p = 0,01. Falta ≥ 1,2× mesmo no melhor caso, então é obrigatório distribuir a verificação por PR (§3) e encurtar T no tier 2.

## 6) Recomendação (ordenada por custo e depois risco)

1. **Lotes com bisseção inteligente e k adaptativo (2–8, k ≈ 5 com p = 0,13)** no trem atual. Custo zero, risco baixo (só latência). Leva a caixa de 36 para ~60 PRs/h processadas (~52 verdes/h) e cumpre 1.000/dia. A bisseção inteligente evita retestar a metade que já se sabe vermelha.
2. **Pré-filtro na lane.** Antes de `pr.ready`, a autora roda o gate no próprio contêiner. Não é prova, só filtro. Custo zero, risco baixo. Baixa o p na caixa para ~0,02 e permite k ≈ 12 (~190 PRs/h, ~4.600/dia).
3. **Ruleset no Origin** exigindo o check do gate no head exato, mais `--match-head-commit`. Custo zero, risco baixo. Hoje o forge não exige nada (`Gates: none required`).
4. **Verificação cruzada entre lanes com prova externa.** O Worker sorteia o verificador (outra lane, outro provedor), guarda a chave do app Origin e posta o check run. A caixa reexecuta uma amostra, mais tudo o que muda o gate. Custo zero, risco médio (desenho novo, pede D-xxx). A capacidade escala com o número de lanes.
5. **Cache por teste atestado no tier 2.** Cumpre a condição de P-43 e roda só as chaves alteradas pela mesclagem. Custo zero, risco médio. É a alavanca de 10× para 10.000/dia.
6. **Oracle A1 (≤ 1 OCPU/6 GB) só como segunda caixa de reserva.** Custo zero em dinheiro, mas pede cartão. Risco alto: corte recente, recuperação por ociosidade, falta de capacidade. Rende ≈ +25–40% de uma caixa.
7. **Não usar:** Cloudflare Containers (pago), fly.io (sem franquia), Render (0,1 CPU), HF Spaces (pago/termos), e2-micro (12× mais lenta, só fallback), Origin CI (sem cota pública) e Actions ou CI de terceiros (regra do motor).

## 7) Fontes

- [E] `origin agent prompt`, `origin agent prompt ci`, `origin agent prompt prs`, `origin pr checks --help`/`--json`, `origin pr merge --help`, `origin ruleset create --help`, `origin repo list`, `origin pr checks 95/100/105/108/109`, `origin ruleset list`, `origin pr requirements 109`, executados em 2026-11-03 (origin 2026.10.28-16-42-28-e1b8407).
- [E] Repositório: `docs/units/engine-forge-origin/research.md`; `scripts/lib/gate_attested.py`, `gate_test_cache.py`, `shared_results.py`; `docs/process/premises/gate-tier2-exact-attested-reuse.yml` (P-43); `docs/domain/DECISIONS.md` (D-073, D-086, D-087, D-119, D-121, D-149); `scripts/cloud/toolchain.json` (checksums arm64).
- [S] Cursor, Origin API: https://cursor.com/docs/api/origin (bloqueado; lido pelo trecho da busca)
- [S] https://www.learncursor.dev/learn/cursor-origin/origin-ci-cd · https://cellcog.ai/blog/what-is-cursor-origin/ · https://starsling.dev/cursor-origin · https://circleci.com/integrations/origin/
- [S] Oracle: https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm · https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/ · https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/ · https://fullmetalbrackets.com/blog/oci-free-tier-breakdown
- [S] Google: https://cloud.google.com/free/docs/compute-getting-started · https://agentdeals.dev/gcp-free-tier-2026
- [S] Cloudflare: https://developers.cloudflare.com/workers/platform/pricing/ · https://developers.cloudflare.com/workers/platform/limits · https://developers.cloudflare.com/containers/platform/pricing/ · https://developers.cloudflare.com/containers/platform/limits/
- [S] https://fly.io/docs/about/discontinued-plans/ · https://community.fly.io/t/confused-about-trial-credits-and-free-allowances/20605 · https://render.com/docs/free · https://huggingface.co/docs/hub/spaces-overview
- [S] Bazel e confiança: https://stripe.com/blog/fast-secure-builds-choose-two · https://groups.google.com/g/bazel-discuss/c/0005BAB_mlI · https://github.com/buchgr/bazel-remote/issues/59 · https://jmmv.dev/2025/09/bazel-remote-execution.html
- [S] SLSA: https://slsa.dev/spec/v1.0/levels · in-toto/rebuilders: https://ssl.engineering.nyu.edu/blog/2019-01-18-in-toto-paris · https://github.com/kpcyrd/rebuilderd
- [S] Filas de merge: Uber SubmitQueue (EuroSys 2019) e "CI at Scale: Lean, Green, and Fast" https://arxiv.org/abs/2501.03440 · https://mergify.com/learn/merge-queue/batching · https://docs.trunk.io/merge-queue/batching · https://mergify.com/blog/dynamic-merge-queue-batch-size
- [I] A conta de lotes (§5) é minha: enumeração exata para k ≤ 12 e Monte Carlo (40 mil lotes) para k > 12, com T = 100 s fixo e falhas independentes.
