# ARQ-SISTEMA — audit

## Entradas

- [intake.md](intake.md): o problema é não distinguir o sistema existente, o ideal e as responsabilidades sobrepostas. Sua métrica exige um universo explícito: não confundo quantidade de arquivos com quantidade de componentes, nem dono de arquivo com dono de operação.
- [research.md](research.md): uso a combinação C4/arc42/DDD/ADR e contratos executáveis como referência de comparação. A pesquisa não determina os achados nem escolhe a arquitetura. Seu primeiro degrau é descrever verificavelmente o hoje após o marco Origin.
- Brief de Daniel de 01/11: a pergunta ordenadora é **o que encarece cada mudança?** Esta entrega contém diagnóstico e causas, sem alternativas, desenho-alvo ou consertos.

Revisão observada: `2d5446c55`, branch `docs/arq-sistema-audit`, worktree `/tmp/wt-arq-audit`. As contagens são desta árvore, antes deste arquivo. Observações remotas têm horário próprio e não representam necessariamente a versão implantada dessa revisão. Origin já tem adaptador e cliente na base; isso não significa que foi selecionado: tanto a leitura efetiva de `config.get` nesta sessão quanto os defaults indicaram `forge-events.adapter=github` e `forge-events.log_adapter=github`. Não declaro concluída uma migração operacional que não observei.

**Método de custo:** arquivos atravessados, unidades envolvidas e implementações da mesma decisão são proxies do trabalho de entender, coordenar e verificar uma mudança. Não há medição causal de minutos por raiz. Nenhum multiplicador abaixo deve ser convertido em minutos ou somado aos demais; raízes podem afetar o mesmo commit. Não executei suites completas, gates ou ações operacionais; só leituras, planos de bateria sem execução e a verificação local de commits.

## Findings

1. **O inventário físico confere, mas não delimita responsabilidades.** `pathlib.Path('scripts').iterdir()`, `is_file`, `os.access(X_OK)` e `glob` produziram: 66 arquivos imediatos, 65 executáveis, 3 diretórios; 178 `.py` imediatos em `scripts/lib`, 35 `gate*.py`, 13 `train*.py`, 8 `forge*.py` somando lib e adapters. `units/*/unit.json`: 47. São recortes de nomes, não 178 sistemas. O universo funcional inspecionado abaixo cobre o caminho mudança → prova → fila → merge e seus serviços, configuração e verificadores. Não é um inventário de todas as funções da biblioteca.

   | Componente observado | Operações e relações observadas | Unidade/dono observado |
   |---|---|---|
   | Entrada de push | inventário, testes selecionados, alerta de sobreposição; consulta a porta | `engine-push-guard` / `engine-lane` |
   | Gate e composição do lote | seleção, união, execução e prova; recebe cabeças do trem | `engine-gate-verdict` para `gate_batch.py` / `engine-lane` |
   | Trem e workspace Git | fila, admissão, composição, julgamento e solicitação de merge | `engine-train` / `engine-lane` |
   | Porta de eventos/forja | envelope, validação, replay, roteamento e operações de PR | `engine-events` / `engine-lane` |
   | Adaptador GitHub | comentários, metadados, revisões, status, merge e locks | `engine-forge-github` / `engine-lane` |
   | Adaptador e cliente Origin | metadados/revisões/status; diário no control plane; merge em GitRefs | `engine-forge-origin` / `engine-lane` |
   | Configuração | registro e replay de overrides; lida também pela construção das portas | `engine-config` / `engine-lane` |
   | Unidades e bateria | posse de caminhos, grafo de imports, seleção de provas por unidade | `engine-units` / `engine-lane` |
   | Runner/control plane | descoberta e execução de jobs; claim/lease/heartbeat e estado operacional | `engine-service` / `engine-lane` |

   Evidência: `scripts/lib/prepush.py:426`, `scripts/lib/gate_batch.py:65`, `scripts/lib/train.py:224`, `scripts/lib/forge_events.py:313`, `scripts/lib/forge_github.py:106`, `scripts/lib/forge_origin.py:57`, `scripts/lib/config.py:1`, `scripts/lib/unit_check.py:1`, `scripts/lib/unit_battery.py:89`, `scripts/lib/service_runner.py:1`, `services/control-plane/src/core.js:448`; atribuição por `units.unit_of(path)` e manifestos. As linhas de finalidade dos manifestos e as operações concretas delimitam este recorte; não há nessa amostra um contrato de exclusividade por operação.

2. **O custo de atravessar fronteiras já aparece no histórico, apesar do dono único.** Comando de amostragem: `git log --no-merges -n 100 --format=COMMIT:%H --name-only 2d5446c55`. Separei blocos por `COMMIT:`, contei caminhos não vazios e unidades distintas com `units.unit_of(path)` da árvore auditada, descartando `None`. Resultado nos 100 commits: mediana 2 arquivos, máximo 41; mediana 0 unidades, máximo 3; 25 cruzam unidades. No subconjunto de 29 commits com pelo menos um caminho em `scripts/` ou `services/`, excetuando `scripts/tests/` como critério de inclusão: **mediana 5 arquivos e 2 unidades; 20/29 cruzam unidades**, máximos 41 arquivos e 3 unidades. Os arquivos acompanhantes de teste/docs entram na contagem de arquivos.

   Exemplos conferidos pelos mesmos blocos: `8a198a73e` atravessa 41 arquivos e 3 unidades (`engine-config`, `engine-events`, `engine-forge-origin`); `be3f6071b`, 5 arquivos nas mesmas 3; `8a3a7172f`, 15 arquivos em `engine-config`, `engine-events`, `engine-service`. São commits, não uma amostra de PRs completos; não afirmo uma mediana por PR nem que todo cruzamento seja indevido. O mapa atual pode não atribuir arquivos já apagados e por isso subconta unidades históricas. **Custo observado:** uma mudança de código desta amostra exige normalmente ler cinco arquivos e coordenar duas unidades, mesmo sem uma segunda identidade de dono.

3. **Os 47 limites de posse de arquivos não se tornam limites semânticos de operação.** A leitura JSON de todos os manifestos encontrou 47 `cell=engine`, 47 `owner=engine-lane` e também 47 valores efetivos `lane`/`owner=engine-lane`; zero campos `contract`, cinco campos `battery`. `train_ownership.py:48-67` deriva a lane dos caminhos; `:82-100` só consulta `approvals()` se o dono/lane de uma unidade tocada difere da lane recebida. Logo, para mudanças reconhecidas como `engine-lane` nesta configuração, `foreign=[]` e a consulta não ocorre. Isso não significa que a função nunca pode recusar uma lane arbitrária ou uma configuração futura.

   `unit_check.py:63-113` garante posse única de caminhos e `:131-145` verifica `requires`, não quem pode executar a operação de compor um lote ou registrar um veredito. A exclusividade de arquivo está implementada; a de responsabilidade não se deduz dela. **Custo:** 47 unidades continuam chegando à mesma identidade para coordenação; os 20/29 commits multiunidade de F2 não ativam por isso uma aprovação estrangeira. Cada discussão de responsabilidade atravessada precisa ser resolvida fora desse sinal automático. Raiz R1.

4. **Dois componentes constroem a mesma união; a segunda construção é parte da prova da primeira.** `train.py:224-239` chama `workspace.combine` em cada membro; `train_git.py:108-138` implementa `merge-tree`/`commit-tree`, com data determinística dos pais. Já `gate_batch.py:65-80` implementa outro laço de `merge-tree`/`commit-tree`; `:91-101` reconstrói a união mesmo quando recebe `head`, e `given_head` em `:118` compara a árvore. A chamada é ligada por `scripts/gate-batch:3-5,29` e pelo default `train.tier2_command=['scripts/gate-batch','--tier','2']`.

   Há uma finalidade legítima de conferir a árvore recebida; isso não elimina a duplicação do mecanismo de combinação. As implementações também diferem: determinismo dos timestamps e tratamento de erro sem arquivo de conflito estão explícitos em `train_git.py:108-138`, enquanto a outra tem seu próprio tratamento. **Custo:** uma alteração de semântica de composição tem dois algoritmos em duas unidades que precisam concordar, passando por três arquivos Python (`train.py`, `train_git.py`, `gate_batch.py`) e pelo wrapper de ligação. Para um lote limpo de N membros, os dois laços fazem N combinações cada, antes de considerar rebuilds. Não medi sua duração nem proponho retirar a conferência. Raiz R2.

5. **As contagens de armazenamentos, merges e detectores misturavam capacidades distintas.**

   - Diário: `forge_events.py:88,116,152-172,175,208,257-285` contém memória, arquivo, GitHub, git-ref, control e seleção Origin, além de board/roteamento. Origin delega `append/read` a `ControlAdapter` (`forge_origin.py:61,107-111`); board é uma projeção: primeiro persiste no log git-ref e depois renderiza comentários (`forge_events.py:175-205`). Não são seis cópias independentes do mesmo diário em execução. A configuração lida nesta sessão foi GitHub para porta/log, board 0 e arquivo para `engine.step.measured` e `gate.started`. A existência de alternativas por si só não é defeito; **o custo verificável é reconstruir a topologia a partir de três chaves de seleção e da lista de kinds**, além da delegação interna do adaptador.
   - Merge: há três implementações disponíveis: helper `gh pr merge` em `forge_github.py:381-389`; push de commit de merge em `forge_git_ref.py:139-155`; endpoint API em `forge_origin_client.py:294`. O caminho Origin da porta chama GitRefs (`forge_origin.py:128-143`), não o endpoint. O cliente documenta que esse endpoint não é usado pelo adaptador e que mirrors recusam merge (`forge_origin_client.py:294-301`). O GitHub selecionado usa o primeiro, via `github_api.run_http`: o shim interpreta os argumentos `gh pr merge` e faz a requisição REST (`github_api.py:456-485`), sem executar esse subprocesso. Três implementações não são três mergers simultâneos. **Custo:** a invariável de head exato aparece nos três caminhos; uma mudança dessa garantia tem três lugares para comparar, embora só dois sejam selecionados pelos adaptadores inspecionados.
   - Sobreposição: `prepush.py:426` define `open_pulls`, usado por `overlap` em `:462-486`. Não existe `scripts/lib/open_pulls.py`. Esse par é um único caminho de alerta por arquivos comuns. Rebuild do trem (`train.py:424-458`) trata avanço da base/recusa da forja; `train_admit.py:128` trata sobreposição de shards. Não provei três detectores da mesma condição. Alerta de mesmo arquivo, conflito Git e sobreposição de provas são perguntas diferentes. Só a composição de F4 é duplicação operacional demonstrada neste recorte. Raízes R2/R3; estas ressalvas limitam suas conclusões.

6. **A porta comum reúne consumidores muito diferentes, com cobertura desigual por adaptador.** O trem chega a `change/open_changes/merge/approvals` (`train.py:179,192-197,461` e `train_queue.py`); a porta também expõe `open_pulls`, `pull`, commits, abertura/fechamento, comentários, status, identidade e locks (`forge_events.py:445-530`). AST das classes contou **24 métodos públicos diretamente definidos em GitHubAdapter e 9 em OriginAdapter**, incluindo operações auxiliares e de diário; não confirma o número dez. O docstring da porta ainda descreve a interface como append/read/recent/change (`forge_events.py:7-17`).

   Consumidores concretos: AST das chamadas `port.*` de `replay_branch.py` encontrou `change_commits`, `close_change`, `comment`, `find_change`, `open_change`, `pull`; `prepush.py` usa `open_pulls`; `stall_report.py` usa `comments`, `open_changes`, `pull`, `pushes`, além do diário; `lessons.py` usa `emit/read`. Portanto também não são seis operações extras só para esses consumidores. `ForgeEvents._operation` (`forge_events.py:449-453`) descobre falta de método na hora da chamada; Origin não define, por exemplo, `open_pulls` ou `open_change`.

   Há ainda uma segunda fronteira em migração: `scripts/lib/adapters/engine-vendors.json:29-53` permite **13 sites de baseline GitHub** fora dos adaptadores, incluindo `commit_check`, `structure`, `premises`, `idea_to_prod`, `release_policy` e `gate_policy`. `vendor_check.py:1-14` distingue essas exceções dos novos acessos proibidos. Assim a frase de `PORTS.md:3-6` sobre todo acesso passar pela porta é uma intenção parcialmente aplicada, não o desenho operacional completo. **Custo:** trocar uma operação da forja requer comparar ao menos duas superfícies de adaptador e os consumidores; trocar a forja do fluxo exige ainda examinar 13 exceções autorizadas. A amostra F2 mostra mudanças Origin reais em três unidades. Raiz R3.

7. **A verificação de fronteira não cobre a ligação dinâmica que seleciona adaptadores.** `unit_map.py:27-28,120-144` extrai imports Python por regex, sem `importlib.import_module`. `forge_events.py:152-169` seleciona GitHub/control/Origin por import dinâmico. Com `OU_CONFIG_STORE=file`, `unit_map.Code(Path('.').resolve(),log='').edges['scripts/lib/forge_events.py']` retornou somente `branch_age.py`, `config.py`, `event_contracts.py`, `forge_board.py`, `forge_git_ref.py`; **não retornou `forge_origin.py`, `forge_control.py` ou `forge_github.py`**. O manifesto de `engine-events` declara apenas `requires={'engine-config':'^1'}`. A ligação dinâmica é intencionalmente usada para não declarar dependência do vendedor (comentário em `forge_events.py:153`); o finding é a diferença entre ligação real e garantia anunciada de todo import em `UNITS.md`, não a afirmação de que dependência de vendedor deveria ser obrigatória.

   `unit_check.py:132-145` julga o grafo assim medido, não a compatibilidade das operações de plugins carregados. `rules` e `ring` tampouco dão esse limite ao engine: `docs/architecture/UNITS.md:86-98` declara sua desativação após D-111/D-113. **Custo:** ao alterar a seleção, são necessários dois inventários de relações (imports reconhecidos e seleção dinâmica); uma validação de `requires` verde não elimina a investigação manual das três ligações ausentes acima. Raiz R4.

8. **A prova por unidade pode ser vazia embora existam testes no gate por outra associação.** Não interpreto cinco campos `battery` como cinco unidades testáveis. `unit_battery.py:89-126` deriva os passos dos arquivos pertencentes à unidade e dos consumidores de contrato. Planos consultados, sem executar testes:

   ```text
   OU_CONFIG_STORE=file; unit_battery.plan('engine-events')       -> script-tests: 4 arquivos .test.sh
   OU_CONFIG_STORE=file; unit_battery.plan('engine-train')        -> script-tests: 4 arquivos .test.sh
   OU_CONFIG_STORE=file; unit_battery.plan('engine-forge-origin') -> []
   ```

   A invocação foi um processo Python com `sys.path.insert(0,'scripts/lib')`, import de `unit_battery` e chamadas a `plan`. `units/engine-forge-origin/unit.json:6-15` possui apenas docs e dois módulos de produção. Seus testes existem: `scripts/tests/covers/forge-events.json:16-17,30` associa os módulos Origin e seu teste live ao conjunto forge-events. Não afirmo falta global de testes nem executei bateria vazia para chamá-la de verde. **Custo:** uma mudança Origin obriga consultar o manifesto da unidade e o covers de outra bateria para saber qual prova realmente executar (dois mapas de associação); o comando de plano da própria unidade não fornece nenhum passo. Raiz R5.

9. **Há arquitetura documental que não corresponde aos caminhos existentes, e a contagem de artefatos não mede sua fidelidade.** `AGGREGATES.md:12-16,23-27` apresenta como leitores atuais `scripts/check-architecture.mjs` e `scripts/lib/gate_suite.py`, e os alvos contexts/intents/gate-suite-renames; os dois arquivos não existem na árvore (`Path.is_file() == False`). `UNITS.md:86-98` explica a saída do checker e dos slots com a OU, ao contrário daquela tabela. `PORTS.md:11` coloca Origin como slot enquanto `forge_origin.py:57` e `forge_origin_client.py:201-235` já implementam adaptador/cliente. Seu catálogo continua com nove vendedores, dois active, seis slot e um forbidden (leitura de `engine-vendors.json`); esses estados não equivalem ao inventário de portas ou adaptadores atuais. `STRUCTURE.md:99-102,122-123,141` ainda atribui recusas ao checker e a `ship-verify`, retirados conforme D-111 (`DECISIONS.md`, linha D-111).

   Reconferência com diretórios imediatos de `docs/units`: **176 pastas; intake 20, research 20, audit 168, plan 166, retro 157; 39 retros contêm `timeline|linha do tempo` (regex case-insensitive), 16 arquivos `docs/process/lessons/*.yml`**. Antes havia 175/19; a abertura ARQ explica o acréscimo. Regex mede menção, não qualidade da linha do tempo; regras de intake não são retroativas (`STRUCTURE.md:86-94`). `docs/capabilities/CAP-*.md`: 12, com `status:` approved 7, done 3, requested 2. Nem status aprovado nem arquivo presente provam a arquitetura efetiva. Na validação desta entrega, `scripts/structure-check --pr-body /tmp/arq-sistema-audit-pr-body.md` saiu 0 com 17 warnings; três eram recusas convertidas em aviso pelo regime de exceção (dois planos sem esforço válido e FORGE-PORT/R2 com só dois porquês). `structure.py:720-724,755` implementa essa conversão, autorizada por D-260; não é um bypass criado por esta sessão. Portanto “0 errors” nesse modo também não prova que todas as regras escritas estão sendo recusantes. **Custo:** a pergunta “quem verifica a arquitetura hoje?” exige reconciliar pelo menos três documentos (`AGGREGATES`, `UNITS`, `STRUCTURE`) com os arquivos; a pergunta de adaptador ainda inclui `PORTS`. Raiz R6.

10. **Disponibilidade do control plane não é disponibilidade do executor; há estados operacionais distintos.** GETs read-only em 01/11, `22:25:11.687Z` (19:25 BRT), para o default de `service.control_url`, com `User-Agent` do default `service.user_agent`, produziram:

    ```text
    /healthz 200 ok
    /readyz  200 {"ready": true}
    /status: health.status=warn, runner=null, transport=control, paused=false
    runners: probe heartbeat=2026-10-30T12:51:52.519Z
             the-tower-runner kind=vm heartbeat=2026-11-01T00:14:56.751Z
    metrics.jobs: queued=867, leased=0, cancelling=0
    queue: 648 entradas; window: events=300, complete=true
    merges: inclui #1057 em 2026-11-01T22:21:01.315Z, repetida duas vezes
    ```

    Método: `urllib.request.Request(base+path,headers={'User-Agent':agent})`, `urlopen(timeout=15)`, parse JSON; base/agent lidos de `config/registry/service/service.control_url.json` e `service.user_agent.json`. Sem esse User-Agent os três GETs responderam 403; o próprio registro do User-Agent documenta o comportamento. Não considero esses 403 prova de serviço fora do ar. Não li tokens.

    Localmente, `Path('.gate/service/state.json').exists()` retornou `False`; `ps -eo comm,args` não mostrou `service_runner.py` ou `train serve` fora do próprio comando de inspeção. Isso não exclui executores em outras máquinas ou com outro transporte. O status remoto demonstra heartbeats antigos dos runners registrados e nenhum job leased nesse instante, **não ausência mundial de execução**: os merges recentes impedem essa conclusão. As 648 entradas de queue não são 648 PRs atuais bloqueados, nem 867 jobs queued equivalem a esse total. `services/control-plane/src/core.js:670-674` faz readyz depender de secrets, enquanto `:540-541` avalia idade de heartbeat separadamente; `service_status.py:85-89,191-198` lê estado local com outro escopo. `docs/operations/services.md:17-21,65-77` descreve o transporte Git e a visão local, além da alternativa control. **Custo:** para saber se uma mudança aguardando gate será executada, há ao menos duas fontes de estado (checkout e control plane) e uma terceira evidência de entrega (eventos de merge), sem equivalência de fila/saúde entre elas. A observação exige reconciliá-las; não atribuo os tempos de entrega publicados a esta causa. Raiz R7.

## Causas raiz

### R1. A decomposição por arquivos não expressa exclusividade de operações

Cadeia de porquês:
1. Por que atravessar duas unidades não explicita outra responsabilidade a coordenar? Todas as 47 têm a mesma lane efetiva.
2. Por que o trem não pede outra aprovação nesses cruzamentos? A regra compara a identidade da lane, não operações ou contextos semânticos.
3. Por que a posse única não decide quem compõe ou publica uma prova? Seu objeto é um caminho de arquivo; duas funções em arquivos diferentes podem realizar a mesma operação sem disputar caminho.
4. Por que a declaração de unidade não fecha essa lacuna? Nenhuma declara contrato e os checks inspecionados julgam caminhos/imports, sem inventário de operações exclusivas. A decomposição controlada pelo repositório tem granularidade de arquivo/lane, insuficiente para expressar aquela propriedade.

Classe: arquitetura/desenho

Evidência: F1–F4; `train_ownership.py:48-100`, `unit_check.py:63-145`, 47 manifestos.

Custo em tempo de mudança (proxy): 20/29 commits de código da amostra atravessam unidades; mediana 2 unidades/5 arquivos. O dono único não resolve automaticamente a divisão de responsabilidade. Não há minutos atribuíveis medidos.

### R2. Composição e verificação da união possuem mecanismos independentes

Cadeia de porquês:
1. Por que uma mudança na composição exige conferir duas implementações? Trem e gate têm seus próprios laços de merge.
2. Por que o segundo laço roda mesmo com um head fornecido? O gate reconstrói uma árvore para conferir a união declarada pelo trem.
3. Por que essa conferência também repete decisões de erro e construção de commit? Seu mecanismo implementa o merge em vez de apenas consumir o resultado do workspace; o workspace possui outra implementação dessas decisões.
4. Por que a divergência pode persistir sem violar a posse de unidade? São arquivos legitimamente possuídos por unidades diferentes; a arquitetura observada atribui às duas a composição sem um único contrato da semântica compartilhada.

Classe: arquitetura/desenho

Evidência: F4–F5; `train.py:224-239`, `train_git.py:108-138`, `gate_batch.py:65-101`, `scripts/gate-batch:3-5`.

Custo em tempo de mudança (proxy): 2 algoritmos em 2 unidades, 3 módulos Python e 1 wrapper de ligação a conferir; 2N combinações no lote limpo descrito em F4. Sem duração medida.

### R3. Uma mesma porta admite capacidades parciais sem representar sua compatibilidade no limite

Cadeia de porquês:
1. Por que selecionar Origin não prova que o fluxo inteiro usa as mesmas operações? Seus nove métodos públicos não cobrem os consumidores que GitHub atende com 24.
2. Por que isso não é recusado ao selecionar o adaptador? `_operation` procura cada método apenas quando o consumidor o chama.
3. Por que a interface nominal não basta? A porta originalmente descrita como diário também concentra manutenção de PR, status, identidade e locks; seus consumidores exigem subconjuntos diferentes.
4. Por que “todos usam a porta” também não prova substituição completa? O vendor check aceita 13 sites externos como baseline de migração.
5. Por que essas duas propriedades deixam custo recorrente? A fronteira controlada hoje expressa uma fábrica e exceções de acesso, mas não a matriz de compatibilidade das operações exigidas pelo fluxo. Seleção única, cobertura de métodos e fim da migração são propriedades distintas.

Classe: mecanismo faltando

Evidência: F5–F6; `forge_events.py:7-17,449-453`, classes `GitHubAdapter` e `OriginAdapter`, `engine-vendors.json:29-53`, `vendor_check.py:1-14`.

Custo em tempo de mudança (proxy): comparar 2 superfícies de adaptador, consumidores de pelo menos 3 fluxos adicionais (push, replay, stall) e 13 exceções ao trocar a forja. Mudanças Origin observadas atravessam 3 unidades (F2). Não são 24 métodos obrigatórios em toda porta, nem tempo cronometrado.

### R4. O contrato verificado cobre imports reconhecidos, não todas as ligações de execução

Cadeia de porquês:
1. Por que uma ligação efetiva a Origin não aparece no grafo de `requires`? Ela usa `importlib.import_module`, fora da regex de imports.
2. Por que a recusa de dependência não a encontra por outro caminho? `unit_check` recebe o grafo produzido por esse extrator.
3. Por que o limite declarado continua mais amplo que a prova? A documentação fala em todo import entre unidades, mas o carregamento de adaptadores deliberadamente fica fora dessa representação de dependência estática.
4. Por que isso é uma causa estrutural controlável, e não erro da regex isolada? Existem dois tipos de relação — import estático e seleção dinâmica — e o modelo executável inspecionado só representa o primeiro; nenhuma garantia inspecionada cobre a compatibilidade operacional do segundo.

Classe: mecanismo faltando

Evidência: F7; `unit_map.py:27-28,120-144`, `unit_check.py:132-145`, `forge_events.py:152-169`.

Custo em tempo de mudança (proxy): 2 inventários de relações a conferir; 3 ligações reais ausentes do grafo no caso medido (GitHub/control/Origin). Um `requires` verde não encerra essa investigação. Sem minutos medidos.

### R5. Posse de código e associação de provas por unidade usam critérios diferentes

Cadeia de porquês:
1. Por que pedir o plano da bateria Origin retorna zero passos? Seus caminhos não incluem testes selecionáveis nem contrato.
2. Por que os testes existentes não entram por conhecerem esse código? O covers de forge-events associa testes à produção, mas `unit_battery.plan` seleciona por arquivos possuídos e contratos dos consumidores.
3. Por que ter dois mapas causa uma lacuna observável? A associação de cobertura do gate não equivale à pertença à unidade, e não é consumida nessa seleção.
4. Por que o estado é permitido? O mecanismo aceita uma lista vazia de passos; no modelo inspecionado não há exigência de que toda unidade de produção tenha uma prova própria não vazia coerente com o covers.

Classe: regra faltando

Evidência: F8; `unit_battery.py:39-51,89-126`, `units/engine-forge-origin/unit.json:6-15`, `scripts/tests/covers/forge-events.json:16-17,30`.

Custo em tempo de mudança (proxy): 2 mapas de testes precisam ser reconciliados numa mudança Origin, cujo plano por unidade tem 0 passos. Não implica ausência de testes globais nem tempo de execução aferido.

### R6. A validade das descrições não está ligada à sobrevivência das relações que descrevem

Cadeia de porquês:
1. Por que consultar a arquitetura fornece leitores que já saíram? AGGREGATES conserva relações com checker e gate_suite retirados.
2. Por que outra página pode simultaneamente declarar sua retirada? UNITS registra a saída com OU, enquanto as relações são repetidas em documentos independentes.
3. Por que a contagem de documentos/status não detecta essa divergência? Ela mede presença e estado editorial, não a existência do leitor nem a operação que ele verifica.
4. Por que retirar o checker não invalida automaticamente as garantias repetidas? Os checks observados de unidades/vendors julgam código e catálogos, não a verdade de afirmações operacionais em tabelas e prosa. Falta vínculo executável entre essas descrições e os fatos que condicionam sua validade.

Classe: mecanismo faltando

Evidência: F9; `AGGREGATES.md:12-27`, `UNITS.md:86-98`, `PORTS.md:11`, `STRUCTURE.md:99-102,122-123,141`, D-111.

Custo em tempo de mudança (proxy): ao menos 3 documentos para reconciliar quem verifica arquitetura, 4 incluindo seleção de forja. As 168 auditorias e 166 planos não medem essa fidelidade; sem minutos atribuíveis.

### R7. As visões de prontidão, execução e entrega têm escopos diferentes

Cadeia de porquês:
1. Por que readyz pode passar com todos os runners registrados antigos? O endpoint verifica secrets; heartbeat é outra checagem, que apenas avisa.
2. Por que ausência de estado local também não encerra o diagnóstico? Ela só descreve esta máquina; o control plane mantém seu próprio registro remoto.
3. Por que queue, jobs e merges não resolvem essa dúvida por uma única contagem? São coleções com semânticas diferentes; havia jobs queued, zero leased e merges recentes simultaneamente.
4. Por que a pergunta “quem executará esta mudança?” exige essa reconciliação? Transporte Git e control, prontidão do serviço, posse de job e prova de entrega não têm equivalência no modelo observado. A fronteira de observabilidade controlada pelo repositório permite saúde parcial sem demonstrar disponibilidade do caminho completo.

Classe: arquitetura/desenho

Evidência: F10; `service_status.py:85-89,191-198`, `services/control-plane/src/core.js:540-541,670-674`, `service_runner.py:1-16`, snapshot remoto de 22:25:11.687Z.

Custo em tempo de mudança (proxy): ao menos 2 fontes de estado e eventos de entrega a conciliar antes de atribuir uma espera; 867 jobs queued e 0 leased no snapshot são exposição operacional, não minutos perdidos nem 867 mudanças bloqueadas comprovadas. Tempos de heartbeat não medem duração de mudança.

## Distância do estado da arte

Já temos decisões com provas (DECISIONS/structure), contrato de eventos e validação de envelopes, configuração centralizada, unidades com posse única e `requires`, verificação de vendedores com baseline e seleção por covers. Há mecanismos reais de separação, não ausência de arquitetura. O mapeamento funcional de F1 e as relações de F4–F10 aproximam a vista de componentes/cenários de C4 e arc42; não equiparo cada script a um contexto DDD.

Falta coerência entre as vistas estática, dinâmica e operacional: posse de arquivos não demonstra exclusividade de operações; o grafo não representa a seleção dinâmica; baterias por unidade e covers têm mapas distintos; descrições sobrevivem a leitores retirados. A existência de ADRs não substitui a descrição do hoje; a análise de imports sozinha não recusaria os dois combinadores independentes. Portanto a distância da referência não se resume a adotar uma ferramenta.

Estamos **no primeiro degrau, ainda parcial** da escada da pesquisa: esta auditoria identifica revisão, recorte funcional, responsáveis observados, relações, uma duplicação demonstrada e lacunas explícitas. Não completou um censo de todas as operações do engine nem verificou Origin selecionado em operação. Não há base para declarar os quatro contadores de resolvido do intake zerados. No recorte, há pelo menos uma responsabilidade implementada por dois componentes (composição da união), mas não uma contagem global confiável de todas as duplicações. Há donos de caminhos; donos exclusivos de operações não estão demonstrados. O ideal separado (degrau 2) e provas de recusa operacional (degrau 3) não são produtos desta auditoria. Não escolho alternativas aqui.

## Base defects expected

- **KD-3ec4be1f**, aberto, dono `engine-lane`, unidade `engine-config`: evento inválido no change store pode causar `config.StoreError`. Evidência: `docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml:2-13`. O registro é histórico; não reproduzi a falha nesta sessão. Os outros dois registros versionados (`KD-024bbecb` e `KD-4db6e693`) estão resolved, não os contabilizo como abertos.
- **F4, F6–F9:** dívida arquitetural/documental observada na base, atribuída pelos manifestos a `engine-train`, `engine-gate-verdict`, `engine-events`, `engine-forge-github`, `engine-forge-origin`, `engine-units` e `engine-structure`, todos `engine-lane`. A estrutura documental cabe a A Torre (`STRUCTURE.md:12-18`). São achados desta auditoria, não novos KDs registrados nem falhas de teste reproduzidas.
- **F10:** heartbeats remotos antigos e visões de saúde divergentes no instante observado; dono dos caminhos de runner/control plane `engine-service` / `engine-lane`. Nenhum serviço foi iniciado, parado ou reparado; não classifico o control plane como ausente.
- A validação de estrutura encontrou também avisos de base: caminhos inexistentes nos manifestos engine-budgets/coordinator/generate, unidades config/coordinator/flow/train acima do teto e três recusas levantadas pelo regime (F9). Dono dos manifestos: `engine-lane`; política de exceção: Daniel/D-260. Nenhum desses avisos foi corrigido nesta entrega.
- Verificação barata de base executada: `python3 scripts/lib/commit_check.py --local` → exit 0, `local-checks: 0 refusal(s), 4017 ms`. Isso não equivale à bateria completa nem elimina os limites acima.

Premises: none
