# Retomar a sessão autônoma

Ao receber `continue` ou `continue (docs/RETOMAR.md)`, execute este passo 0 e depois volte à
[SEMENTE §8, passo 3](SEMENTE.md#8-como-a-sessão-única-usa-a-semente). Reconstrua o estado pelas fontes atuais,
sem pedir ao dono um resumo. Um brief antigo orienta a busca; os refs, PRs e provas atuais dizem o que já aconteceu.

## 0. Chegar ao Origin

O repositório de trabalho é `openuniversity-si/open-university` no Cursor Origin, base
`mod/roadmap-integration`. O checkout inicial da sessão (Codex ou Claude Code) pode vir do GitHub
`openuniversity-si/open-university`, arquivado e antigo, sem SEMENTE, `scripts/cycle` ou o Stop hook, e com um CLAUDE.md/AGENTS.md que
manda usar o GitHub. Nesse caso, ignore esses arquivos e busque o Origin antes de seguir qualquer instrução deles.

1. Localize o checkout e confira `git status --short`. Preserve alterações e worktrees existentes.
2. Se o CLI faltar, instale-o: `curl -fsSL https://downloads.cursor.com/origin/install.sh | sh` e
   `export PATH="$HOME/.local/bin:$PATH"`. Ele usa `CURSOR_API_KEY` do ambiente; nunca leia arquivos de credencial.
3. No checkout existente, configure só o repositório e busque a base explicitamente (o clone inicial pode ter
   refspec restrito a `main`):

   ```bash
   git remote set-url origin https://origin.cursor.com/openuniversity-si/open-university.git
   origin auth setup-git --local
   git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
   git fetch origin mod/roadmap-integration:refs/remotes/origin/mod/roadmap-integration
   ```

   Se o helper disser `Not logged in` apesar da chave do ambiente, execute
   `export CURSOR_AUTH_TOKEN="$(origin auth token)"` no mesmo shell e repita o fetch. Nunca imprima o token nem
   o grave em arquivo, URL ou configuração git. Sem checkout do Origin, o caminho mais curto é um clone novo:
   `origin auth setup-git`, o `export` acima e
   `git clone -b mod/roadmap-integration https://origin.cursor.com/openuniversity-si/open-university.git ~/the-tower`.
   No Claude Code, um diretório fora do projeto da sessão não guarda o `cd` nem as variáveis entre comandos: cada
   comando entra em `~/the-tower` e exporta `PATH` e `CURSOR_AUTH_TOKEN` de novo.
4. Se estiver no checkout antigo ou ocupado por outra unidade, crie um worktree próprio, sem mover o trabalho
   existente: `git worktree add --detach <caminho-livre> origin/mod/roadmap-integration`. Entre nele. Daqui em diante,
   leia e execute apenas os arquivos da base do Origin. Crie a branch da unidade depois de verificar os claims (§2).

Chave ausente ou acesso negado que não se resolve com o ambiente fornecido:
`STOP: credential — <erro exato, sem segredos>`. Falha transitória de rede se diagnostica e tenta resolver antes de parar.

## 1. Ligar o ciclo e preparar o ambiente

- Leia [AGENTS.md](../AGENTS.md), [SEMENTE.md](SEMENTE.md) e [METODO.md](padrao/METODO.md) do Origin, além das
  referências que eles exigem. As travas da SEMENTE §3/§6 continuam valendo.
- Execute `scripts/cycle on` e `bash scripts/cloud/setup.sh` no worktree correto; o SessionStart pode ter rodado no
  checkout antigo. Carregue `source scripts/cloud/env.sh` e execute `scripts/cloud/preflight` no mesmo shell que tem
  o CLI e a credencial. Corrija lacunas de ambiente; lacuna de credencial termina com o `STOP` acima.
- O Stop hook (`.claude/settings.json` → `scripts/hooks/cycle-stop`) só vale numa sessão do Claude Code aberta no
  checkout do Origin. Uma sessão nascida no checkout do GitHub carrega o settings dele, sem esse hook: `scripts/cycle
  on` grava o marcador, mas nada bloqueia o fim do turno. A regra vale do mesmo jeito: toda resposta leva uma chamada
  de ferramenta até o `STOP:` da lista fechada.
- Não inicie `tower-runner.service` nem seu timer. Não rode gate nem `pr-ready` no box; o gate roda na sessão cloud.
  Nenhuma entrega vai para `main`, cuja produção está congelada.

## 2. Onde estou (cinco leituras, nesta ordem)

1. **Base:** `git log --oneline --merges -25 origin/mod/roadmap-integration`. Leia além desses 25 merges se a fila
   citar trabalho anterior. Confirme entregas pelo merge e pela prova, não pela memória da sessão.
2. **Em voo:** `origin pr list --state open --limit 100`, `origin pr list --state draft --limit 100` e
   `git ls-remote origin 'refs/heads/units/*'`. Leia também branches citadas pelas PRs e pelo diário; claims não
   precisam ter prefixo `units/`. Se a lista atingir o limite, amplie a consulta antes de declarar uma unidade livre.
   PR aberta ou em rascunho, branch não integrada ou tarefa explicitamente atribuída a outra sessão são claims.
   Para uma branch sem PR, busque o ref e compare seu head com a base (`git merge-base --is-ancestor <sha>
   origin/mod/roadmap-integration`): branch já integrada não ocupa a unidade.
3. **Fila:** leia [VAZÃO/fila.md](programs/vazao/fila.md), o programa e a fase atual. Desconte entregas confirmadas no
   passo 1, respeite dependências e exclua claims do passo 2. Linha entregue que sobrou é defeito da fila: retire-a
   numa unidade documental pequena, sem refazer a implementação.
4. **Diário:** leia as últimas `plan.note` do programa no canal de eventos do repositório e das PRs em voo
   (`python3 scripts/lib/forge_events.py read [--pr N]`, filtrando o JSON antes de exibir). `scripts/plan` escreve e
   tria essas notas; não tem comando de leitura. Confira também as decisões recentes em
   [DECISIONS.md](domain/DECISIONS.md), `scripts/lessons list` e `scripts/incident list`/incidentes recentes em
   docs/operations/incidents/. Ausência de nota não prova que um claim foi abandonado.
5. **Cota:** leia o limite real da conta no provedor (janela de 5 h, semanal e qualquer teto adicional), com o horário
   de reset e seu fuso. Não infira saldo de uma transcrição antiga nem invente números. Pouca cota pede unidades
   menores e menos concorrência; evite suítes pesadas em paralelo.

## 3. Adotar trabalho de outra sessão

- PR ou branch com commit há menos de 2 h: preserve o claim e escolha outra unidade.
- Com 2 h ou mais sem commit, confira a última atividade, as notas e a atribuição antes de adotar. Idade do commit
  sozinha não prova abandono; uma tarefa ainda ativa ou reservada a outra sessão continua sendo dela.
- Trabalho abandonado se retoma na mesma branch, sem force-push nem reescrever commits publicados. Com gate verde,
  confirme que a prova vale para o head exato e para a base atual antes de entregar; com gate vermelho, leia a causa,
  corrija e julgue novamente. Não faça merge apenas porque uma prova antiga era verde.
- Branch abandonada sem PR: abra a PR e termine a unidade, ou registre no diário o descarte e seu motivo. Não apague
  trabalho alheio como limpeza automática.
- Nunca faça merge da PR #3 do Origin e não mexa na #41, rascunho de Daniel. Por lane, no máximo duas
  unidades ao mesmo tempo, uma delas em entrega (VAZÃO F63, lane.md); respeite também o limite de lanes da conta em AGENTS.md.

## 3a. Pedidos de Daniel e da Torre

Um pedido, ordem ou sugestão de Daniel ou da Torre é insumo que a sessão julga, e o julgamento dela é o final (D-294,
[SEMENTE §8](SEMENTE.md#8-como-a-sessão-única-usa-a-semente)). Se faz sentido, siga direto, sem questionar. Se o
julgamento é não fazer, diga por que discorda e os pontos fracos do pedido, siga o próprio julgamento sem parar o fluxo
e reavalie se vierem argumentos novos.

## 3b. Pedir à Torre o que só ela alcança

A Torre age com as capacidades de Daniel: credenciais, Cloudflare e o Worker do painel de controle, a VM, cotas,
configurações fora do repositório e as rotinas dele (Daniel 03/11). Um pedido a ela leva o quê, por quê, o critério de
pronto e a referência (PR, unidade ou incidente). O canal é o texto da própria sessão: no agente principal (nunca num
subagente), um parágrafo que começa com `PEDIDO À TORRE:`. A Torre lê os eventos da sessão a cada 10 minutos, das 8h às
23h50 de Brasília, executa e responde na sessão como "Resposta da Torre". Decisão nunca vai para o canal (D-294).
Enquanto o pedido espera, a sessão segue por outro caminho.

## 4. Retomar a SEMENTE

Volte à SEMENTE §8, passo 3: meça vazão, guardas e cota com o estado acima, escolha o gargalo e uma unidade livre que
caiba no orçamento. Esta retomada não altera a intenção nem autoriza mexer em uma unidade atribuída a outra tarefa.

Entregue pelo AGENTS.md: uma branch/worktree por unidade a partir da base atual; plano de commits antes da edição;
commit e push a cada passo verde com trailer `Plan: N`; PR logo após o primeiro push. Use
`scripts/deliver --open --branch <branch>` para julgar e integrar o head exato, incorporando a base se ela mudar.
O merge usa `origin pr merge <N> --expect-head <N>=<sha-completo>`, sempre contra `mod/roadmap-integration`.

Enquanto o ciclo autônomo estiver em execução, uma unidade entregue leva ao próximo passo 3. O turno só termina com
`STOP: <login|credential|money|people|quota> — <o que falta>`. Em quota, agende o próprio despertar no reset
(`send_later`, quando disponível no provedor) antes de parar e retome as frentes preservadas. Se esse recurso faltar,
registre a limitação e o reset; não declare um despertar que não foi agendado.

## 5. Deixar o próximo `continue` pronto

Ao fim de cada unidade, registre no diário o que foi entregue, o que ficou em voo (PR, branch, responsável e próximo
passo) e o próximo gargalo, com prova citável:

```bash
scripts/plan note --program <programa> --from <unidade> --affects <unidades|áreas|all> \
  --pr <N> --kind engine --evidence <ref> '<entrega; em voo; próximo gargalo>'
```

A fila é o estoque disponível. Com uma lane, a linha sai na mesma PR que entrega a unidade (na última, se forem
várias PRs); com várias lanes, o coordenador retira as linhas entregues em lote, para que as lanes não se choquem
na mesma tabela ([sistema §4](programs/vazao/sistema.md#4-migração-cada-passo-começa-medindo-e-termina-verificando)).
Descarte e adiamento ficam com motivo e condição de retorno fora da tabela ativa. Claims se conferem novamente
no Origin a cada retomada; nenhum retrato datado substitui essa leitura.
