# COMPARTILHAMENTO — intake

## Pedido
Daniel, 01/11/2026, nos turnos t3329u e t3332u, repassado por A Torre às 17:45 BRT: "por que a gente tá com tanto problema de liberação do trem, cara?" e "não é só o trem, o lock não, tem uma série de arquivozinhos compartilhados que tão dando problema. Então talvez o redesenho e a classe que a gente tem que fazer é compartilhamento de arquivo. E são arquivos que não são de código... arquivos de documentação, arquivos de decisão, arquivo dessas coisinhas, de regrinha, e fica travando a gente. Será que não vale a pena um estudo de como as melhores do mundo fazem isso? Pra gente ter uma resolução completa desse problema?" t3333u e t3334u pedem o estudo pelo Codex ou pelo cloud. t3302u, regra permanente: a unidade nasce o próprio requisito da própria pesquisa. Entregar o objetivo e a medição. O desenho e o critério de aceitação ficam para depois da pesquisa.

## Intenção
Uma resolução da classe inteira: o arquivo compartilhado que não é código, e que dois PRs editam ao mesmo tempo. O estudo olha como organizações que já operam nessa escala tratam o arquivo, para o desenho sair daí.

## Contexto
O pedido separa duas coisas que andam juntas no dia a dia. O lock do trem segura a fila por segundos. O que para o merge é o arquivo que todo mundo tem de alterar para a mudança existir: o índice de decisões, o inventário, o manifesto da unidade, o diário operacional, a chave de registro que ainda mora num agregado editado à mão.

No HEAD `8c82c11bb` de `origin/mod/roadmap-integration` (01/11 17:28 BRT) a casa já partiu uma família e não as outras. D-099 e D-101 montam o agregado de `config/registry/<dono>.json` a partir de um arquivo por chave, e `.gitattributes` marca esse agregado com `merge=regenerate`. D-217 grava cada decisão nova em `docs/domain/decisions/D-NNN.md`. D-242 recusa linha nova digitada na tabela. A tabela `docs/domain/DECISIONS.md` continua no git, e o passo que a gera a partir dos registros ainda não substituiu o arquivo. `docs/structure/assets.json` e `units/*/unit.json` continuam editados no mesmo commit do código. `CODEOWNERS` é gerado dos manifestos e também carrega `merge=regenerate`.

A medição que confere o pedido, com o comando e o que divergiu do recado, está na pesquisa. O desenho não está.

## Regras
- D-077 e o Padrão v7: esta pasta leva `intake.md` e `research.md` antes de `audit.md` e `plan.md`. A pesquisa não escolhe o mecanismo e não escreve critério de aceitação.
- t3302u: o requisito da unidade nasce da pesquisa dela. Este passo entrega o objetivo e a linha de base medida.
- D-054: produção congelada. Esta unidade não mexe em produção.
- D-009: sem GitHub Actions. Um mecanismo cujo único veículo é um workflow do GitHub não entra como está.
- D-217, D-242, D-099 e D-101 já valem: registro por arquivo, tabela sem linha digitada à mão, agregado de registro regenerado no merge. A pesquisa lê esses mecanismos como o que a casa já fez, não como o desenho desta unidade.

## Problema real
Dois PRs que precisam registrar um fato no mesmo arquivo, e esse arquivo não é código, param um no outro no merge. Resolvido, medido no branch de integração do mesmo jeito que a pesquisa mediu, é essa classe deixar de ser a maioria das linhas de conflito. O número de hoje está na pesquisa. O mecanismo que faz a parcela cair não está.

## Lacunas
- O lock do trem (rodadas, mediana, total do dia) e a espera dos PRs (abertos, mergeados, mediana, os que passaram de 3 h) não estão no `git log`. Não reconferi esses quatro grupos. A frase do Daniel de que o lock não é o gargalo fica de pé como pedido; a conta do lock fica aberta.
- A página `sapling-scm.com/docs/introduction/motivation` respondeu 404. O que está na pesquisa sobre a Sapling saiu do post de engenharia de 15/11/2022 e de `sapling-scm.com/docs/introduction`.
- Não achei, no anúncio do GVFS (Microsoft, 2017), um mecanismo que parta um arquivo de índice. O texto trata do tamanho da cópia de trabalho. Se a Microsoft publica outro documento só sobre o arquivo que todo mundo edita, ele não entrou nesta leitura.
