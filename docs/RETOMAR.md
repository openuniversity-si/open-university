# Retomar a sessão autônoma

Ao receber `continue` ou `continue (docs/RETOMAR.md)`, execute este passo 0 e depois volte à
[SEMENTE §8, passo 3](SEMENTE.md#8-como-a-sessão-única-usa-a-semente). Reconstrua o estado pelas fontes atuais,
sem pedir ao dono um resumo. Um brief antigo orienta a busca; os refs, PRs e provas atuais dizem o que já aconteceu.

## 0. Chegar à base no GitHub

O repositório de trabalho é `openuniversity-si/open-university` no GitHub, base `main` (D-314, desde 14/11/2026). O
Origin é só um espelho de leitura do `main`, num repositório só da Open University: nada se busca nem se entrega lá. O
histórico antigo (`mod/roadmap-integration` no Origin) é a era anterior; um brief ou nota que mande buscá-lo é dessa
era.

1. Localize o checkout e confira `git status --short`. Preserve alterações e worktrees existentes.
2. Confira que `origin` é o GitHub (`git remote get-url origin` → `https://github.com/openuniversity-si/open-university`)
   e busque a base: `git fetch origin main`. Se `origin` apontar para o Origin (um setup antigo o reescrevia), volte-o:
   `git remote set-url origin https://github.com/openuniversity-si/open-university`.
3. Se o checkout estiver ocupado por outra unidade, crie um worktree próprio, sem mover o trabalho existente:
   `git worktree add --detach <caminho-livre> origin/main`. Crie a branch da unidade depois de verificar os claims (§2).

Acesso negado ao GitHub que não se resolve com o ambiente fornecido: `STOP: credential — <erro exato, sem segredos>`.
Falha transitória de rede se diagnostica e tenta resolver antes de parar.

## 1. Ligar o ciclo e preparar o ambiente

- Leia [AGENTS.md](../AGENTS.md), [SEMENTE.md](SEMENTE.md) e [METODO.md](padrao/METODO.md) da base, além das
  referências que eles exigem. As travas da SEMENTE §3/§6 continuam valendo.
- Execute `scripts/cycle on` e `bash scripts/cloud/setup.sh` no worktree correto; o SessionStart pode ter rodado no
  checkout antigo. Carregue `source scripts/cloud/env.sh` e execute `scripts/cloud/preflight` no mesmo shell que tem
  o CLI e a credencial. Corrija lacunas de ambiente; lacuna de credencial termina com o `STOP` acima.
- O Stop hook (`.claude/settings.json` → `scripts/hooks/cycle-stop`) só vale numa sessão do Claude Code aberta no
  checkout deste repositório; numa sessão que não o carrega, `scripts/cycle on` grava o marcador, mas nada bloqueia o
  fim do turno. A regra vale do mesmo jeito: toda resposta leva uma chamada de ferramenta até o `STOP:` da lista
  fechada.
- O gate da AWS está desligado (D-314): não inicie `tower-runner` nem o `tower-runner.service` do box. O gate é o
  check `tower/gate` do GitHub (`scripts/verify-commit`, que a sessão também roda localmente com `--no-post`); a
  entrega vai para `main` só pela merge queue.

## 2. Onde estou (cinco leituras, nesta ordem)

1. **Base:** `git log --oneline --merges -25 origin/main`. Leia além desses 25 merges se a fila
   citar trabalho anterior. Confirme entregas pelo merge e pela prova, não pela memória da sessão.
2. **Em voo:** as PRs abertas e em rascunho do GitHub (`gh api 'repos/openuniversity-si/open-university/pulls?state=open&per_page=100'`,
   com `draft` no JSON) e `git ls-remote origin 'refs/heads/*'`. Leia também branches citadas pelas PRs e pelo diário; claims não
   precisam ter prefixo `units/`. Se a lista atingir o limite, amplie a consulta antes de declarar uma unidade livre.
   PR aberta ou em rascunho, branch não integrada ou tarefa explicitamente atribuída a outra sessão são claims.
   Para uma branch sem PR, busque o ref e compare seu head com a base (`git merge-base --is-ancestor <sha>
   origin/main`): branch já integrada não ocupa a unidade.
3. **Fila e programa ativo:** leia o programa corrente (`docs/programs/padrao-dev/`), o espaço do problema
   (`config/problem/`) e a saída de `scripts/model measure`. Os programas legados da era Origin (incluindo
   `docs/programs/vazao/fila.md`, arquivado sob D-314) são histórico e não são a fila viva. Desconte entregas
   confirmadas no passo 1, respeite dependências e exclua claims do passo 2.
4. **Estado, decisões e histórico:** confira `scripts/model measure`, `scripts/deploy status`, as decisões recentes em
   [DECISIONS.md](domain/DECISIONS.md) e `docs/domain/decisions/`, e `scripts/lessons list`. Nota: o diretório
   `docs/operations/incidents/` é local e ignorado no git (`.gitignore`), e o diário `forge_events` / `train/events` da
   era Origin está dormente (D-314); não trate ausência de arquivo local como prova de zero incidentes nem de claim
   abandonado.
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
- As PRs do Origin (a #3, a #41 rascunho de Daniel, as #721 a #723) são da era anterior: não se mexe nelas. Por lane, no máximo duas
  unidades ao mesmo tempo, uma delas em entrega (VAZÃO F63, lane.md); respeite também o limite de lanes da conta em AGENTS.md.

## 3a. Pedidos de Daniel e da Torre

Um pedido, ordem ou sugestão de Daniel ou da Torre é insumo que a sessão julga, e o julgamento dela é o final (D-294,
[SEMENTE §8](SEMENTE.md#8-como-a-sessão-única-usa-a-semente)). Se faz sentido, siga direto, sem questionar. Se o
julgamento é não fazer, diga por que discorda e os pontos fracos do pedido, siga o próprio julgamento sem parar o fluxo
e reavalie se vierem argumentos novos.

## 3b. Pedir à Torre o que só ela alcança

A Torre age com as capacidades de Daniel: credenciais, workflows e rulesets do GitHub (D-087), configurações de conta
AWS/Cloudflare fora do repositório, cotas e as rotinas dele (Daniel 03/11; o Worker do painel de controle na Cloudflare
foi aposentado por D-323 e a VM do runner está parada desde D-314). Um pedido a ela leva o quê, por quê, o critério de
pronto e a referência (PR, unidade ou incidente). O canal é o texto da própria sessão: no agente principal (nunca num
subagente), um parágrafo que começa com `PEDIDO À TORRE:`. A Torre lê os eventos da sessão a cada 10 minutos, das 8h às
23h50 de Brasília, executa e responde na sessão como "Resposta da Torre". Decisão nunca vai para o canal (D-294).
Enquanto o pedido espera, a sessão segue por outro caminho.

## 4. Retomar a SEMENTE

Volte à SEMENTE §8, passo 3: meça vazão, guardas e cota com o estado acima, escolha o gargalo e uma unidade livre que
caiba no orçamento. Esta retomada não altera a intenção nem autoriza mexer em uma unidade atribuída a outra tarefa.

Entregue pelo AGENTS.md: uma branch/worktree por unidade a partir da base atual; plano de commits antes da edição;
commit e push a cada passo verde com trailer `Plan: N`; PR contra `main` logo após o primeiro push, com auto-merge
ligado. O `tower/gate` julga o head e o commit da merge queue, e a fila faz o merge; vermelho se corrige na branch,
com merge do `main` (nunca rebase nem force push). Depois do merge, acompanhe o deploy que ele toca
(`scripts/deploy status`).

Enquanto o ciclo autônomo estiver em execução, uma unidade entregue leva ao próximo passo 3. O turno só termina com
`STOP: <login|credential|money|people|quota> — <o que falta>`. Em quota, agende o próprio despertar no reset
(`send_later`, quando disponível no provedor) antes de parar e retome as frentes preservadas. Se esse recurso faltar,
registre a limitação e o reset; não declare um despertar que não foi agendado.

## 5. Deixar o próximo `continue` pronto

Ao fim de cada unidade, deixe o registro no histórico do repositório (merge commit em `main`, provas da PR, estado do
programa ativo e `scripts/deploy status`), e quando houver nota de diário em sessão local registre com prova citável:

```bash
scripts/plan note --program <programa> --from <unidade> --affects <unidades|áreas|all> \
  --pr <N> --kind engine --evidence <ref> '<entrega; em voo; próximo gargalo>'
```

Os programas legados da era Origin (como `vazao/fila.md` e `vazao/sistema.md`) ficam arquivados como histórico (D-314).
Claims se conferem novamente no GitHub a cada retomada; nenhum retrato datado substitui essa leitura.
