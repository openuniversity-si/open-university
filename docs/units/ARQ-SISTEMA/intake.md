# ARQ-SISTEMA — intake

## Pedido

Daniel, 01/11/2026, 18:43 BRT:

> Já deixa como pendência que a gente tem que abrir com uma unidade de análise geral de arquitetura do projeto. Eu tenho a ideia que tá uma zona, nós não temos nossos sistemas nem o ideal definido, muito menos como é que tá hoje, eles tão sobrepondo, tá virando uma zona isso aí.

Correção de método, logo depois:

> esses ajustes não é pra você fazer aqui, é pra você abrir uma seção, seja no codex ou em outro lugar, e seguir.

## Intenção

Tornar compreensíveis o sistema que temos, o que queremos e as responsabilidades que hoje se sobrepõem, para que decisões de arquitetura tenham uma base verificável. Abrir a unidade de análise geral, sem aproveitar sua abertura para ajustar componentes ou escolher uma arquitetura.

## Contexto

A Torre é o motor de entrega; Open University saiu deste repositório. A ordem vigente de Daniel (01/11, 18:06 BRT) é resolver o Origin primeiro e realizar esta análise logo depois: medir antes da resolução da forja seria medir o sistema antigo. Esta abertura registra a pendência; a medição arquitetural posterior depende desse marco.

A medição fornecida na sessão foi feita em 01/11, entre 18:20 e 18:50 BRT, no checkout principal. As contagens abaixo foram reconferidas apenas nesta worktree, na árvore de `a2c3f63dd`, cujo conserto documental parte da base `86d541f020`:

- `scripts/`: 66 arquivos no primeiro nível, 65 executáveis e `release-policy.json` não executável; 3 subdiretórios. Contagem por arquivos, permissão de execução e diretórios imediatos.
- `scripts/lib/`: 178 arquivos `.py` diretamente no diretório; 35 correspondem a `gate*.py`, 13 a `train*.py`. São 8 arquivos `forge*.py` somando esse nível e `scripts/lib/adapters/`. Esses recortes por nome não são fronteiras de responsabilidade.
- `units/*/unit.json`: 47 manifestos; todos declaram `cell: engine` e `owner: engine-lane`. Desses, 5 declaram `battery`; declaração não comprova execução ou cobertura.

A conferência corrige dois pontos do relato recebido: são 3 subdiretórios imediatos em `scripts/`, não 4, e não se sustenta a afirmação de que nenhuma unidade tem bateria declarada. Não houve inspeção de outras worktrees nem nova medição de processos ou serviços.

O levantamento recebido também aponta alternativas de armazenamento de eventos, caminhos de merge e detecção de sobreposição, além de distância entre a arquitetura descrita em `docs/architecture/PORTS.md` e `docs/architecture/UNITS.md` e a operação efetiva. São sinais que motivam a unidade, não conclusões de auditoria ou uma causa-raiz já demonstrada por esta abertura. Quantidade de arquivos, por si só, não mede operações duplicadas.

## Regras

D-077 e o [Padrão v8](../../padrao/v8/intake-and-research.md): intake traduz o pedido; pesquisa olha para fora; cada etapa entrega um produto independente. D-081 reserva a investigação das causas à auditoria e a comparação de alternativas ao plano, em outra sessão. Nesta entrega existem somente intake e pesquisa, em commits próprios após a branch e a PR em rascunho.

O requisito nasce da pesquisa (Daniel, t3302u, 01/11, 16:18 BRT). Esta abertura não fixa desenho-alvo, critérios de aceitação da implementação, componentes a cortar ou tarefa para a auditoria. A métrica abaixo traduz o resultado desejado pelo pedido, sem escolher seu mecanismo. D-054 mantém a proibição de mudanças manuais em produção; a PR segue aberta para o trem, sem merge pela sessão.

Premises: none

## Problema real

Não temos o ideal definido, não temos a descrição de como o sistema está hoje e seus componentes se sobrepõem sem uma decisão explícita de responsabilidade.

Medição de resolvido: contar componentes sem fronteira declarada, operações sem um dono nomeado, operações duplicadas entre componentes e fronteiras cuja verificação não recusa uma operação de outro componente; cada contagem chega a zero, com o universo de componentes e operações identificado para evitar um zero por omissão. A contagem inicial de operações duplicadas ainda não foi estabelecida; arquivos com nomes parecidos não são essa contagem. O modo de verificar e as fronteiras não estão escolhidos aqui.

## Lacunas

A descrição desejada e seus compromissos ainda não estão estabelecidos; dependem da pesquisa e das decisões de Daniel quando houver alternativas fundamentadas. O pedido e a ordem de prioridade estão claros o suficiente para esta abertura.

A descrição efetiva após o Origin, o universo de componentes e operações, os donos efetivos e a contagem de sobreposições dependem da observação do sistema naquela base. A declaração uniforme de dono não demonstra, sozinha, como a responsabilidade é exercida. Também não foi verificado aqui se as baterias declaradas são operantes. Esta sessão não preenche essas lacunas com uma auditoria antecipada.
