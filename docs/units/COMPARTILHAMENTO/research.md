# COMPARTILHAMENTO — research

Medido em `origin/mod/roadmap-integration`, HEAD `8c82c11bb` (01/11/2026 17:28 BRT). Cada fonte abaixo foi aberta. O que a página não diz, esta pesquisa não inventa.

## Quem já resolveu

### Registro de decisão, um arquivo por decisão

- adr-tools ([README](https://github.com/npryce/adr-tools/blob/master/README.md), [`adr-new`](https://github.com/npryce/adr-tools/blob/master/src/adr-new)). `adr init` cria o diretório e o primeiro registro. `adr new` olha o maior prefixo numérico do diretório, soma um, e grava `NNNN-slug.md` a partir de um template no estilo do artigo do Michael Nygard que o próprio README cita. `-s` marca o registro antigo como superado: o comando edita o arquivo velho e o novo. Mecanismo: o fato mora num arquivo. Custo: o número é um contador compartilhado (`maxid + 1` lido do diretório no instante do comando); dois `adr new` no mesmo snapshot recebem o mesmo número. Superar uma decisão reabre um arquivo que outra pessoa pode estar editando. O README não descreve um índice gerado.

- MADR ([adr.github.io/madr](https://adr.github.io/madr/)). Um template Markdown por decisão, arquivo `NNNN-titulo.md` dentro de `docs/decisions`, número com teto assumido de 9.999 por repositório. Em projeto grande a própria documentação recomenda subpastas por categoria (backend, ui): o número deixa de ser único no repositório e passa a ser único na pasta, de preferência com o mesmo corte da arquitetura. A página, na seção de abordagem automática, ainda diz que não havia ferramenta para o MADR 3.0.0; a notícia do topo anuncia o 4.0.0 como template. Mecanismo: convenção de arquivo e de pasta, não um serviço. Custo: quem escolhe o `NNNN` à mão colide; quem categoriza cedo paga uma meta-decisão; achar uma decisão sem índice é busca no diretório.

- Backstage, ADRs do próprio projeto ([docs/architecture-decisions](https://backstage.io/docs/architecture-decisions/)). O registro nasce sem número: copia-se o template para `adr000-minha-decisao.md`, abre-se o PR, e o número só é atribuído no fim. O registro não se apaga; o antigo ganha "superseded by". No merge, o caminho entra em dois índices editados à mão, `sidebars.ts` e `mkdocs.yml`. Mecanismo: tira o contador do caminho quente durante a revisão. Custo: o número e os dois índices continuam sendo edição humana no momento em que o PR fecha, que é quando vários ADRs fecham juntos.

### Changelog e release, sem cada PR editar o mesmo arquivo

- Keep a Changelog ([keepachangelog.com/en/1.1.0](https://keepachangelog.com/en/1.1.0/)). Um `CHANGELOG.md` curado, para humanos, com seção `Unreleased` no topo. Na hora do release, o conteúdo de `Unreleased` vira a seção da versão. Princípios: uma entrada por versão, tipos fixos (Added, Changed, Deprecated, Removed, Fixed, Security), data ISO. Mecanismo: formato de um arquivo só. Custo: todo PR que quer aparecer no changelog edita o mesmo `Unreleased`. A página ensina o formato e diz que o changelog é para humanos, não para máquinas. Não descreve merge.

- Changesets ([FAQ atual](https://changesets.dev/faq), e o guia do repositório [adding a changeset](https://github.com/changesets/changesets/blob/main/docs/adding-a-changeset.md)). Quem muda o código roda o CLI e commita um Markdown novo em `.changeset/`, com nome aleatório legível para não colidir, front matter com o pacote e o tipo semver, e o texto do changelog. Vários changesets no mesmo PR são o desenho. `changeset version` consome todos, escreve o changelog, sobe a versão e apaga os arquivos. Mecanismo: o PR não toca o changelog; toca um arquivo que só ele cria. Custo: a escrita do changelog e da versão concentra-se num comando só, em geral um PR de release. Esse PR é serial. O FAQ avisa que `.changeset/` é mau lugar para qualquer outra coisa, porque o version apaga o diretório lógico dos arquivos consumidos.

- release-please ([README](https://github.com/googleapis/release-please/blob/main/README.md), [manifest](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md)). Lê a história em [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) e abre um Release PR que é o único a atualizar `CHANGELOG.md`, a versão e a tag. O humano não edita o changelog para a mudança entrar. Monorepo: `.release-please-manifest.json` mais `release-please-config.json`. O documento do manifest diz que editar o manifest à mão só cabe no bootstrap; dali em diante o release-please grava a versão. Custo: disciplina de mensagem de commit; um Release PR aberto de cada vez (o README manda tirar o label `autorelease: pending` de um PR velho antes de nascer outro); o veículo recomendado é GitHub Action. O manifest continua um arquivo. Quem o edita é o robô, não cada PR.

- semantic-release ([README](https://github.com/semantic-release/semantic-release/blob/master/README.md)). No CI, a cada push no branch de release: acha a última tag, classifica os commits desde ela, calcula a próxima versão semver, gera as notas, cria a tag, prepara e publica. Não há seção `Unreleased` editada por pessoa. Custo: CI com credencial, convenção de commit (o default é a do Angular), um job de release. O README não descreve um arquivo de changelog compartilhado como entrada. A entrada é o commit.

- Git, driver `union` ([gitattributes](https://git-scm.com/docs/gitattributes)). Atributo `merge=union`: o merge de três vias fica com as linhas dos dois lados e não escreve marcador. O manual diz que as linhas acrescentadas tendem a sair em ordem aleatória e que a pessoa deve conferir o resultado, e manda não usar sem entender a consequência. O mesmo manual define o driver customizado: o comando recebe `%O %A %B %P`, grava o resultado em `%A` e sai 0 quando fundiu. Mecanismo: o arquivo continua um só; o merge deixa de ser tarefa humana para o caso "os dois lados acrescentaram linhas". Custo: ordem não determinística; não serve para tabela cujo sentido depende da posição da linha.

### Catálogo como dado, não como inventário único

- Backstage, formato do descritor ([descriptor format](https://backstage.io/docs/features/software-catalog/descriptor-format/)). A entidade é YAML ao lado do código (`catalog-info.yaml` é o nome recomendado) e JSON na API. O catálogo ingere o arquivo, processa e só então expõe. `kind: Location` aponta um alvo ou uma lista de alvos, absoluta ou relativa, e a lista pode ser uma hierarquia de diretórios. Mecanismo: cada componente carrega o próprio descritor; o índice que a pessoa consulta é a API, não o arquivo. Custo: um ingest e um banco; uma `Location` que lista todo mundo recria o inventário único. O descritor de um componente continua um arquivo: dois PRs no mesmo `catalog-info.yaml` conflitam como qualquer YAML.

- Spotify, golden path ([engineering.atspotify.com, 2020-08](https://engineering.atspotify.com/2020/08/how-we-use-golden-paths-to-solve-fragmentation-in-our-software-ecosystem), Gary Niemen). O golden path é "the opinionated and supported path to build something", com tutorial passo a passo por disciplina, as ferramentas abençoadas visíveis no Explore do Backstage interno, e o texto em TechDocs. Nasceu de um Hack Week contra o que chamam de rumour-driven development. O golden state, ainda em exploração no texto, é uma lista de checagens de que o sistema está no caminho. Mecanismo: reduz o número de jeitos de fazer a mesma coisa, então reduz o número de convenções que cada time reescreve. Custo: dono do tutorial por disciplina, e o texto tem de mudar no mesmo instante em que a ferramenta muda. Não é um algoritmo de merge. Dois PRs no mesmo tutorial continuam dois PRs no mesmo arquivo. O texto ainda registra o problema de coordenação quando o escritor único saiu e o conteúdo se espalhou por times.

### Política avaliada, não prosa editada

- OPA e Rego ([documentação](https://www.openpolicyagent.org/docs)). OPA separa a decisão da aplicação: o programa manda JSON e recebe uma decisão, que pode ser uma estrutura, não só allow/deny. Rego é a linguagem. Várias regras com o mesmo nome são OU. `input` é o dado da consulta; política e dado não são o mesmo arquivo. Mecanismo: a regra é módulo avaliado, e módulos compõem. Custo: um avaliador no caminho do check; um `.rego` que todo mundo edita continua um arquivo de texto; a contradição aparece na avaliação, não como marcador do git.

- CUE ([introdução](https://cuelang.org/docs/introduction/)). Tipos e valores são a mesma escala. Combinar valores é associativo, comutativo e idempotente: arquivos diferentes podem restringir o mesmo campo, e a ordem não muda o resultado. Dois arquivos que dizem `5` e `6` para o mesmo campo contradizem; `>5` e `<10` fecham. A configuração se separa da computação: o que precisa ser calculado entra como dado misturado, e a ordem dessa mistura não importa. A página situa a origem no GCL do Google e no que a herança daquele modelo não conseguiu ferramentalizar. Mecanismo: o merge do conteúdo é a avaliação, não o hunk. Custo: uma linguagem; uma contradição é erro, e alguém tem de resolvê-la; não há "ficar com as duas linhas".

- Dhall ([dhall-lang.org](https://dhall-lang.org/)). JSON mais funções, tipos e imports, linguagem total, sem efeito colateral, pensada para importar código não confiável. O texto vende uma fonte única referenciada pelos outros arquivos, hash semântico para refatoração que não muda o resultado, e diff semântico. A saída pode ser JSON ou YAML. Mecanismo: a pessoa edita o Dhall pequeno; o JSON grande é gerado. Custo: a linguagem, e o JSON gerado, se for commitado, volta a ser um arquivo só. O site não descreve o merge desse JSON.

### Log append-only e CRDT

- Event sourcing ([Martin Fowler](https://martinfowler.com/eaaDev/EventSourcing.html)). Toda mudança de estado é um evento numa sequência. O estado se reconstrói reexecutando o log; o log pode ser o registro oficial e o estado um cache. Fowler cita um sistema de controle de versão como exemplo, e nota que um log aditivo pede pouco lock. Mecanismo: ninguém edita a linha corrente; acrescenta um evento. Custo: o leitor do estado é uma dobra, não `git show` de uma tabela; replay contra sistema externo precisa de gateway que não repete o efeito. No git, acrescentar no fim do mesmo arquivo não é aditivo: os dois hunks ocupam a mesma região e o merge de texto marca conflito. A forma aditiva dentro do git é um arquivo novo por evento.

- Nix, `flake.lock` ([manual, nix flake](https://nixos.org/manual/nix/stable/command-ref/new-cli/nix3-flake.html)). `flake.nix` declara inputs soltos. O Nix gera `flake.lock`, JSON com o grafo travado (revisão, hash). Quem altera a dependência altera o `flake.nix` ou roda `nix flake update`; o lock é reescrito. Mecanismo: arquivo gerado, commitado por reprodutibilidade, não editado como prosa. Custo: dois PRs que atualizam inputs diferentes reescrevem o mesmo JSON e conflitam. A resolução é gerar de novo, não fundir o JSON à mão. O manual não chama isso de estratégia de merge; descreve o lock como função dos inputs.

- Automerge ([automerge.org/docs/hello](https://automerge.org/docs/hello/)). CRDT: cada ponta edita offline, e o merge automático chega no mesmo estado sem servidor central. O próprio texto compara com o git e diz que o git só funde texto, enquanto o Automerge funde estruturas. Estado imutável, histórico, branches. Mecanismo: o mesmo documento aceita edição concorrente. Custo: um runtime e um formato próprio. Um blob Automerge commitado no git conflita por inteiro, a menos que um merge driver aplique o CRDT. Faz sentido quando duas pessoas editam o mesmo texto. É maquinaria demais para "acrescentar um registro novo", que já é um arquivo novo.

- Yjs ([docs.yjs.dev](https://docs.yjs.dev/)). CRDT com tipos compartilhados (`Map`, `Array`, texto). A ordem em que as atualizações chegam não muda o resultado; não precisa de uma fonte única central. Mecanismo e custo iguais aos do Automerge, com ecossistema de editores. A página não fala de monorepo nem de `git merge`.

### Propriedade: manifesto declarado e propriedade derivada

- GitHub CODEOWNERS ([about code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)). Um arquivo, em `.github/`, na raiz ou em `docs/`. Padrão no estilo gitignore, última linha que casa ganha, donos pedidos na revisão do PR. Com a proteção ligada, um dono basta. O arquivo tem teto de 3 MB; acima disso o GitHub não carrega. A página recomenda curinga para encolher o arquivo, e dono para o próprio CODEOWNERS. Mecanismo: roteia revisão. Não funde conteúdo. Custo: o arquivo é único por branch; dois PRs que acrescentam dono conflitam nele. A página trata isso como sintaxe, não como problema de merge.

- Gerrit, plugin code-owners ([about](https://gerrit.googlesource.com/plugins/code-owners/+/refs/heads/master/resources/Documentation/about.md), [config](https://gerrit.googlesource.com/plugins/code-owners/+/refs/heads/master/resources/Documentation/config.md)). O submit exige aprovação de dono para cada arquivo tocado. Os donos não ficam na config do plugin; ficam em arquivos `OWNERS` na árvore. A config fala em herança do dono pai, que o arquivo pode desligar, em aprovação por arquivo (sticky por arquivo, não pelo change inteiro) e em fallback `NONE` ou `ALL_USERS` para caminho sem dono. O about recomenda o plugin só quando pastas têm donos diferentes; se o repositório inteiro é das mesmas pessoas, permissão comum do Gerrit chega. Mecanismo: propriedade por arquivo da árvore, herdada, cobrada no submit. Custo: cada `OWNERS` é um arquivo editável; a raiz quente diminui porque o dono mora perto do código. Não funde o arquivo de código.

- Chromium, OWNERS ([code reviews](https://chromium.googlesource.com/chromium/src/+/main/docs/code_reviews.md)). Um `OWNERS` por diretório, recursivo até `set noparent`. `per-file` restringe a um glob. `file://` inclui outro arquivo de donos. `*` faz de todo committer um dono. A página prefere muitos diretórios com poucos donos a um diretório grande com muitos. `git cl owners` e o Gerrit acham o dono. Há também `DIR_METADATA` para achar quem entende o código, ao lado do `git blame`. Mecanismo: parte o arquivo de donos na fronteira do diretório. Custo: um arquivo que todo o repositório edita (um índice único) continua com um conjunto de donos só. A página organiza a revisão, não o hunk.

- Linux, `MAINTAINERS` ([documentação renderizada](https://www.kernel.org/doc/html/latest/process/maintainers.html)). Um arquivo. Cada subsistema é uma seção com `M:` (para quem mandar o patch), `R:`, `L:`, `F:` (glob de arquivos), `X:` (exclusão), `N:` (regex). `scripts/get_maintainer.pl` lê isso: com casa em `F:` não olha o `git log`; com casa em `N:` olha o histórico para avisar quem assinou commit. Mecanismo: propriedade derivada de um índice declarado, usada para escolher destinatário. Custo: o índice é um arquivo que o patch de um subsistema novo edita. A página descreve o formato e o script. Não descreve uma partição do arquivo nem um gerador.

### O arquivo quente no monorepo grande

- Google, Piper ([Potvin e Levenberg, CACM](https://cacm.acm.org/research/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)). Um tronco, commits numa ordem serial, a maioria das pessoas trabalha no head. CitC mostra o repositório inteiro e guarda no workspace só o arquivo modificado (a média citada é menos de 10 arquivos). Dono por diretório: a revisão de qualidade e a aprovação do dono são passos diferentes. Rosie parte uma mudança larga na fronteira do diretório, testa, pede revisão ao dono daquele pedaço e commita. O artigo é de 2016, com o retrato do repositório em janeiro de 2015. Mecanismo publicado para o conflito: mudança pequena, no head, em ordem serial, e a mudança larga não é um patch só. Não há, nesse artigo, CRDT nem "o arquivo de índice é gerado". Um arquivo que dois workspaces editam continua um merge.

- Meta, Sapling ([post de 15/11/2022](https://engineering.fb.com/2022/11/15/open-source/sapling-source-control-scalable/), [introdução](https://sapling-scm.com/docs/introduction/)). Cliente compatível com git, feito para o monorepo da Meta (dezenas de milhões de arquivos, commits e branches, com o servidor e o sistema de arquivos virtual). O que o post descreve: smartlog, desfazer, stack de commits com restack, histórico preguiçoso (segmented changelog), EdenFS e sparse profile commitado no repositório para a cópia de trabalho não materializar tudo. A introdução repete o desenho: sempre online, single-master, rebase em vez de merge. Mecanismo: escala a história e a cópia de trabalho, e encolhe o commit. Não remove o conflito textual de um arquivo que dois stacks editam. O restack encontra esse conflito na hora.

- Microsoft, GVFS ([anúncio de 03/02/2017](https://devblogs.microsoft.com/devops/announcing-gvfs-git-virtual-file-system/), Saeed Noursalehi). O repositório do Windows citado: mais de 3,5 milhões de arquivos, mais de 270 GB; clone de 12 h, checkout de 3 h, status de 10 min. O GVFS virtualiza o sistema de arquivos: o arquivo só desce na primeira abertura, e o git ignora o que não hidratou. Com isso o clone cai para minutos e o status para segundos, para um desenvolvedor que mexe em 50–100 mil arquivos de um universo de 3 milhões. Mecanismo: a cópia de trabalho deixa de ser o repositório inteiro. Custo: driver de sistema de arquivos e um protocolo. O anúncio não fala de changelog, OWNERS nem de índice compartilhado.

## Estado da arte

O padrão que se repete, quando o arquivo deixa de travar, tem três formas. Nenhuma das três é "um merge melhor de uma tabela Markdown".

A forma barata e já espalhada: o fato é um arquivo que só aquele PR cria, e o índice é função dos fatos. Changesets faz isso com nome aleatório e um comando que consome. O Nix faz isso com `flake.nix` solto e `flake.lock` gerado. O release-please e o semantic-release fazem o índice (changelog, versão, tag) sair do commit, com um escritor só. O adr-tools e o MADR fazem o fato por arquivo e param no meio: o número ainda é contador, e o Backstage ainda pede dois índices no fim do PR. Keep a Changelog é o formato do arquivo único; fica do lado de cá do problema.

A forma de política: a regra deixa de ser prosa e passa a ser módulo avaliado (Rego) ou valor que se unifica (CUE) ou expressão total que gera o JSON (Dhall). Dois autores compõem se não se contradizem. A contradição é erro de avaliação. Isso pede avaliador no check e uma linguagem. Não pede que o git funda uma tabela.

A forma de registro: o estado é a dobra de um log (Fowler). Dentro do git, o log aditivo é um arquivo por evento, não uma linha a mais no mesmo arquivo. CRDT (Automerge, Yjs) cobre o outro caso, o mesmo texto editado dos dois lados, e só funde sozinho se o runtime participa do merge. Piper, Sapling e GVFS não estão nessa forma. Estão na escala da cópia de trabalho e na disciplina de mudança pequena no tronco. O dono (CODEOWNERS, OWNERS, MAINTAINERS, code-owners) escolhe quem aprova. O arquivo de donos, quando é um só, é ele mesmo o arquivo quente: o GitHub documenta um CODEOWNERS com teto de 3 MB; o kernel mantém um `MAINTAINERS`; o Chromium e o Gerrit espalham `OWNERS` pelo diretório precisamente para a raiz não ser esse arquivo.

O que cada forma exige, em uma linha: a primeira exige um gerador determinístico e a disciplina de não editar o produto; a segunda exige um avaliador e um lugar para a contradição; a terceira exige que o leitor aceite um log no lugar da tabela. O golden path da Spotify não é uma quarta forma. É o jeito de ter menos arquivos compartilhados, porque há um jeito abençoado de fazer a coisa.

## Encaixe em nós

### A conta

Conflitos, no comando `git log --merges --grep=Conflicts: --since='2026-10-02 00:00:00 -0300' --until='2026-11-02 00:00:00 -0300' origin/mod/roadmap-integration`. São 75 merges cuja mensagem contém `Conflicts:`. Três usam a palavra na prosa e não trazem lista `#\t`. Os outros 72 listam 101 caminhos. Oito são `CODEOWNERS`. Os 93 restantes são os 93 do pedido: 20 em código e 73 em arquivo que não é código. O recorte do pedido bate, desde que `CODEOWNERS` fique de fora. Com ele, são 101 linhas, 81 delas fora de código.

Os 20 de código: `scripts/tests/gate-local.test.sh` 5, `scripts/lib/structure.py` 4, e uma vez cada `apps/web/src/media/server/index.ts`, `apps/web/vitest.config.ts`, `scripts/lib/decision_table.py`, `scripts/lib/forge_git_ref.py`, `scripts/lib/repeats.py`, `scripts/tests/memory_git.py`, `scripts/tests/test_decision_table.py`, `scripts/tests/test_gate_areas.py`, `scripts/tests/test_gate_report_skips.py`, `scripts/tests/test_memory_git.py`, `scripts/tests/test_repeats.py`.

Arquivo que não é código, na lista de 101 (o `CODEOWNERS` incluído porque a lista bruta o tem):

| Caminho | Linhas de conflito |
|---|---|
| `docs/domain/DECISIONS.md` | 34 |
| `CODEOWNERS` | 8 |
| `docs/structure/assets.json` | 7 |
| `units/*/unit.json` somados | 10 |
| `docs/operations/incidents.md` | 4 |
| `docs/process/repeats.md` | 3 |
| `docs/process/lane.md` | 2 |
| `config/registry/tests.json` | 2 |
| `scripts/lib/absolute-literals-baseline.json` | 2 |

`units/*/unit.json` por arquivo: `engine-flow` 5, e uma vez cada `engine-gate-ops`, `engine-gate-report`, `engine-gate-run`, `engine-structure`, `engine-train`. O pedido dizia 11. A lista tem 10.

`config/registry/gate.json` e `config/registry/train.json` não aparecem nenhuma vez nessa lista.

Corte no tempo, com o relógio do commit:

| Intervalo | Merges | Linhas | DECISIONS | CODEOWNERS | assets.json | unit.json |
|---|---|---|---|---|---|---|
| Antes de D-099 (30/10 15:05 BRT) | 31 | 39 | 2 | 7 | 2 | 3 |
| De D-099 até D-217 (01/11 00:52 BRT) | 21 | 26 | 17 | 0 | 1 | 3 |
| Depois de D-217 | 23 | 36 | 15 | 1 | 4 | 4 |
| O dia 01/11, desde 00:00 BRT | 32 | 48 | 21 | 1 | 5 | 5 |

Os dois conflitos de `config/registry/tests.json` são de 27/10, antes de D-099. Os dois de `scripts/lib/absolute-literals-baseline.json` são de 26/10. O `CODEOWNERS` do dia 01/11 veio no mesmo merge que `docs/structure/assets.json` e `units/engine-flow/unit.json`.

Churn de 7 dias, commits que não são merge (`git log --name-only` não lista arquivo em merge), de 25/10 17:45 BRT até 01/11 17:45 BRT:

| Caminho | Commits |
|---|---|
| `docs/domain/DECISIONS.md` | 254 |
| `CODEOWNERS` | 185 |
| `docs/structure/assets.json` | 97 |
| `scripts/lib/gate-script-tests.json` | 92 |
| `docs/process/roadmap/STATUS.md` | 78 |
| `docs/process/EVENTS.md` | 50 |
| `config/registry/gate.json` | 50 |
| `docs/process/lane.md` | 45 |
| `config/registry/train.json` | 36 |

O pedido acerta 254, 97, 92, 50, 50, 45 e 36. `STATUS.md` deu 78, não 79. O `gate-script-tests.json` dessa linha é `scripts/lib/gate-script-tests.json`. O de `scripts/tests/covers/` foi tocado 2 vezes na mesma janela. `CODEOWNERS` não estava no pedido e é o segundo arquivo da janela.

Hoje, 01/11 desde 00:00 BRT, `git log --oneline -- docs/domain/DECISIONS.md` lista 88 commits. Esse é o 88 do pedido, e a história simplificada inclui merges. `--no-merges` no mesmo caminho lista 48. O `--name-only` sem pathspec, que não enxerga arquivo em merge, lista 51. São três contagens do mesmo dia. A de 88 mistura o commit que editou a tabela com o merge que a recebeu.

Tamanho, `git ls-files` neste HEAD: `docs/units/**` 567, `config/registry/**` 963, `contracts/**` 205, `docs/process/**` 171 (o pedido dizia 170), `units/*/unit.json` 47. Os 47 manifestos declaram 643 caminhos (o pedido dizia 639). `docs/domain/decisions/D-*.md`: 48 registros (o pedido dizia 49); a pasta tem também `README.md` e `handwritten.txt`. `docs/domain/DECISIONS.md`: 266 linhas, 241 linhas que começam com `| D-` (o pedido dizia 265 linhas e 240 de tabela).

`scripts/lib/merge_regenerate.py` descreve o limite do driver: se a fonte conflita, ou se o git não expõe um único `GITHEAD_<sha>`, o driver cai em `git merge-file` e o conflito continua conflito. O `CODEOWNERS` de 01/11 está nesse caso: a fonte (`units/engine-flow/unit.json`) estava na mesma lista.

### O que já está feito, e o que a lista ainda mostra

O agregado do registro (`gate.json`, `train.json`, e `tests.json` depois de 27/10) é a forma "índice gerado". Churn alto, zero linha de conflito na janela: o commit que mexe na chave regenera o agregado, e o merge do agregado não chega na pessoa. O `CODEOWNERS` é a mesma forma, com a ressalva medida do fallback.

`DECISIONS.md` é a forma pela metade. O fato novo já é `docs/domain/decisions/D-NNN.md` (D-217), e linha digitada à mão já é recusada (D-242). A tabela continua no git, e 15 das 34 linhas de conflito são posteriores ao registro por arquivo. 21 das 34 são do dia 01/11. O contador do número e a linha na tabela continuam no caminho que dois lanes cruzam. Isso é o que o adr-tools deixa aberto (`max+1`) e o que o Backstage empurra para o fim do PR (`sidebars.ts`, `mkdocs.yml`).

`docs/structure/assets.json` não está no `.gitattributes` como `merge=regenerate`. Sete conflitos, quatro deles depois de D-217. É um inventário único, do tipo que o `catalog-info.yaml` foi feito para aposentar, com a ressalva de que uma `Location` única recria o mesmo arquivo.

`units/*/unit.json` já é um arquivo por unidade. O conflito que sobra é dois PRs no mesmo manifesto: `engine-flow` sozinho tem 5 das 10 linhas. Partir o diretório, como o Chromium parte o `OWNERS`, não parte um manifesto que duas mudanças legítimas precisam alongar.

`docs/operations/incidents.md`, `repeats.md`, `lane.md`, e no churn `STATUS.md` e `EVENTS.md`, são diários. Todo append é no mesmo fim de arquivo. O driver `union` é o mecanismo publicado para esse formato, com a ordem instável que o manual do git assume. Um arquivo por evento é a forma aditiva do Fowler dentro do git. Nenhum dos dois está aplicado a esses caminhos.

`scripts/lib/absolute-literals-baseline.json` conflitou duas vezes, as duas em 26/10. É baseline commitado, parente do `flake.lock`: gerado ou reescrito por inteiro, e o merge de texto não tem o que aproveitar.

### Copiar, adaptar, não cabe

- Copiar a forma do changesets e do `flake.lock` para todo índice que já é função de uma fonte. O registro já tem o driver e a prova: `gate.json` com 50 commits e zero conflito, `train.json` com 36 e zero. A fonte tem de ser livre de contador compartilhado, senão o conflito só muda de arquivo. O número `max+1` do adr-tools é o contra-exemplo; o nome aleatório do changeset é o exemplo.
- Adaptar o ADR do Backstage e o MADR por pasta ao registro de decisão. O arquivo por decisão já existe. O que a tabela ainda exige é o índice e o número global. Adiar o número, como o Backstage faz até o merge, ou trocar o número global por um nome que não se lê do diretório, é adaptação. Gerar a tabela no merge, como o agregado do registro, é a outra adaptação, e o fallback do driver já diz quando ela falha: quando a fonte conflita.
- Adaptar o catálogo do Backstage ao `assets.json` e ao manifesto: o descritor mora com o dono, a lista é vista por uma ferramenta. Não cabe importar o golden path da Spotify como mecanismo de merge. Cabe como redução de variedade: menos tipos de arquivo compartilhado, porque há um jeito só de registrar o fato. O texto da Spotify é explícito que isso é tutorial e caminho suportado.
- Adaptar Rego, CUE ou Dhall só onde a "regrinha" já é dado que dois módulos podem compor sem se contradizer. O registro partido por chave já é esse dado, em JSON, com gerador. Trocar o JSON por Rego ou CUE é outra linguagem em cima de uma partição que já tirou o conflito do agregado. O diário operacional não é política: é narrativa. Avaliador não funde narrativa.
- Não cabe CRDT como primeira máquina do registro de decisão. O fato novo não é edição concorrente do mesmo parágrafo; é um registro a mais. Automerge e Yjs pagam um runtime para o caso do mesmo texto. Cabem, se cabem, no diário em que duas pessoas reescrevem o mesmo parágrafo, e só com merge driver. Não cabe guardá-los como blob opaco no git e esperar o merge de texto.
- Não cabe tratar CODEOWNERS, OWNERS ou `MAINTAINERS` como resolução do conflito. Os quatro roteiam aprovação. O kernel mostra o índice único ainda em uso. O Chromium e o Gerrit mostram o índice partido por diretório. O nosso `CODEOWNERS` já é gerado, e a lista de conflito só voltou a citá-lo quando a fonte não fundiu.
- Não cabe esperar que Piper, Sapling ou GVFS dissolvam o arquivo. Os três textos lidos escalam a cópia de trabalho e, no Piper, a ordem serial do tronco e o corte da mudança larga na fronteira do dono. O arquivo que dois PRs editam continua merge de texto. A casa já tem tronco de integração e mudança pequena. O que a lista mede é o arquivo que a mudança pequena ainda é obrigada a tocar.

## Escada de ambição

Do mais barato ao mais estrutural. Este arquivo não escolhe o degrau. A escolha é do `audit.md` e do `plan.md`, com o Daniel, depois desta pesquisa.

1. Gerar o índice em vez de editá-lo. A fonte é o arquivo pequeno que o PR já teria de criar; o índice commitado é reescrito no merge pelo driver que o registro já usa. Vale para a tabela de `DECISIONS.md`, para `assets.json`, para `STATUS.md` e `EVENTS.md` se eles forem dobra de uma fonte, e para o baseline de literais. Custo medido aqui: quando a fonte conflita, o driver devolve o conflito (o `CODEOWNERS` de 01/11). O índice continua no git, porque alguém ainda o lê como arquivo.

2. O fato com nome que não é contador. Um arquivo novo por decisão, por incidente, por entrada de inventário, com identidade que dois PRs no mesmo snapshot não disputam (o nome aleatório do changeset, não o `max+1` do adr-tools). O número global, se ainda fizer falta para a pessoa, sai na geração do índice, não na hora de gravar. Custo: achar o fato sem abrir a tabela passa a ser busca, ou a tabela gerada.

3. O diário que é de fato um log de linhas, com `merge=union`, nos caminhos em que a ordem global não é o sentido (`incidents.md`, `repeats.md`, `lane.md`, se a leitura for "as duas linhas entram"). Custo publicado pelo git: a ordem das linhas acrescentadas não é estável, e alguém confere. Não serve para a tabela de decisão, cujo lugar da linha é o sentido.

4. A regra que o check avalia, no lugar da prosa que o check relê. Rego, CUE ou Dhall, onde duas contribuições compõem ou contradizem. O registro por chave já é a versão JSON disso. O degrau é estender a avaliação para regra que hoje é parágrafo, não reescrever o agregado que já não conflita. Custo: linguagem e avaliador; contradição vira erro, não marcador.

5. O catálogo ingerido. `assets.json` e a lista de caminhos do manifesto deixam de ser o arquivo que o PR alonga; o descritor fica com a unidade, e uma leitura monta a lista, no modelo do `catalog-info.yaml` e da API do Backstage. Custo: um leitor no lugar do JSON único, e cuidado para a `Location` que lista tudo não recriar o arquivo quente. Não resolve dois PRs editando o mesmo `unit.json`, como `engine-flow`.

6. Propriedade por diretório, no modelo OWNERS do Chromium e do code-owners do Gerrit, no lugar de um índice único de donos. O nosso `CODEOWNERS` já é gerado dos manifestos, então o degrau só existe onde o dono ainda é uma lista editada. Custo: roteia revisão, não funde arquivo. `MAINTAINERS` é o lembrete do que acontece se a lista voltar a ser uma.

7. O registro é o log, e a tabela é dobra descartável. Estado oficial no evento (Fowler), dentro do git como um arquivo por evento ou fora dele como log de serviço. O CRDT entra aqui só para o documento que é o mesmo texto dos dois lados, com merge driver. Piper, Sapling e GVFS não são este degrau: são a escala da cópia de trabalho em torno de um arquivo que continua texto. Custo: o leitor deixa de ser o Markdown commitado; a reconstrução e a ordem passam a ser o mecanismo; produção continua fora desta unidade (D-054).
