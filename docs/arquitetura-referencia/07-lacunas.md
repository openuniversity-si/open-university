# 07. Lacunas: a fronteira e o que só A Torre pode responder

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

Entregável 6. O que ninguém fez ainda, o que só a Torre pode responder, e a avaliação das reflexões de Daniel nesta
conversa (que não são ordens; o julgamento é da sessão, D-294).

## 1. A fronteira: o que ninguém publicou

| # | Lacuna | O mais perto que existe | Por que é fronteira |
|---|---|---|---|
| L1 | Um planejador que gera decisões amplificadas de qualidade a 10^3/s, com A ≥ 10^6 | o Rosie do Google faz milhares de mudanças por dia [S3]; as migrações com LLM do Google fizeram 595 mudanças em 12 meses [V28]; a Anthropic mergeia mais de 30 mil mudanças por dia [A17]; a busca do AlphaEvolve gera milhares de candidatos por problema [A24] | ninguém publica D × A perto de 10^9; as maiores taxas publicadas de uma empresa ficam abaixo de uma mudança por segundo (Google ~0,75/s [S2], Anthropic ~0,35/s [A17]) e o GitHub inteiro mergeia ~41 PRs/s [S17] |
| L2 | Certificar transformações gerais de código por ≤ 500 núcleo·s cada, de forma confiável | o Alive prova reescritas do LLVM uma vez [V19]; o Zelkova faz 10^9 consultas SMT por dia sobre políticas [V15]; o Cedar junta prova e teste diferencial [V17] | fora do LLVM e das políticas, ninguém liga uma prova a 10^5–10^6 lugares de código geral; verificação completa custa caro (o seL4: ~12 pessoas-ano para 8.700 linhas [V22]) |
| L3 | Verificação contínua quando entram 10^9 mudanças por segundo | o TAP agrupa ~0,6 mudança/s e acha o culpado com testes instáveis [S4, V11]; o teste especulativo leva a detecção p50 a 37 min [V3] | é 10^9 vezes a taxa do TAP; a meta de detecção (10 min) é melhor que o melhor publicado |
| L4 | Independência semântica entre decisões em voo | conflito sintático por conjunto de leitura e escrita é teoria de banco de dados; o pushrebase do Mononoke o aplica a código [S5] | duas mudanças em arquivos disjuntos podem interferir pelo comportamento; nenhum método barato detecta isso em escala |
| L5 | Qualidade estatística a 10^9 | a regra de três: zero falhas em N dá ~3/N de limite [V26]; provar taxas de falha muito baixas só por teste é inviável [V25] | a 10^9/s, uma taxa de defeito de 10^-9 por PR ainda é um defeito por segundo; a garantia tem que vir da prova, não da amostra |
| L6 | Tokens por decisão ≤ 10^5 | a mediana de uma tarefa de agente hoje é ~10^6 tokens, e a mesma tarefa varia até 30× entre execuções [A10, A11] | a meta pede uma decisão 10× mais enxuta que uma tarefa de agente comum |
| L7 | Agentes imunes a injeção de prompt sem perder utilidade | o CaMeL dá segurança demonstrável em 77 % das tarefas do AgentDojo, contra 84 % sem defesa [X13]; os padrões de desenho de [X14] | a defesa por desenho ainda custa utilidade; a 10^3 decisões/s isso é custo direto |
| L8 | Revisão humana a 10^9 | o SLSA v1.2 exige revisão de código no nível de fonte L4 [X8]; o Binary Authorization for Borg exige um revisor além do autor [X11] | ninguém revisa 10^9 PRs/s; a pergunta é se revisar a decisão (e não a PR) satisfaz quem exige revisão |
| L9 | O que esta sessão não verificou | listado em [04 §9](04-componentes.md#9-o-que-não-foi-verificado-nesta-sessão) | o egress bloqueou a maior parte dos sites primários e a busca parou no limite de 200 por turno |

## 2. O que só A Torre pode responder

Ninguém de fora responde estas perguntas, porque dependem da intenção e do trabalho da Torre:

1. **Existe trabalho útil para 10^9 PRs por segundo, e onde?** Todo o arquivo do Software Heritage equivale a 6 segundos
   de produção em commits ([05 §9](05-orcamento-e-degraus.md#9-a-escala-de-109-contra-o-mundo)), e 10^9/s é ~10^8 vezes
   a taxa de PRs públicas mergeadas hoje [X31]. A conta mostra que, a 10^9, a maior parte das PRs seria trabalho gerado
   por máquina sobre alvos novos (geração a partir de especificação, otimização contínua, variantes, busca de
   programas), não edição de código humano existente. A tese da Torre (a computação do mundo é desperdiçada e a fábrica
   tira o desperdício, semente §3) sugere um alvo: o software que roda a computação do mundo. Responder isso é o
   planejador.
2. **Como o planejador chega a A ≥ 10^6 com T_d ≤ 10^5** (L1, L6): é o núcleo da fase 2.
3. **Como uma decisão vem com um certificado barato** (L2): a escolha da linguagem das transformações, com semântica que
   se prove, é desenho do conjunto de instruções e do planejador, não da infraestrutura.
4. **Qual é a medida de utilidade** que impede a inflação a 10^9 (PC-15, PC-16): a semente diz que a vazão não se
   infla; a 10^9 isso precisa de uma métrica, e a métrica é da Torre.
5. **Como o sistema melhora o próprio padrão** a essa escala (o ciclo intenção → padrão → execução da semente §2): o
   ledger é a retrospectiva de 10^9 PRs por segundo; transformar isso em padrão melhor é inovação, não infraestrutura.

## 3. As reflexões de Daniel, avaliadas

### "Se a lógica for desenhada para 10^9, o resto do problema seria infraestrutura e financiamento."

**Metade verdade.** Com a lógica desenhada para 10^9 (dois níveis, partição pelo conjunto de escrita, validação
otimista, certificar uma vez, ledger fora do forge, células), os passos 2, 4 e 5 e a máquina do passo 3 ficam dentro do
que já foi demonstrado por unidade, e o resto é frota e dinheiro: ~US$ 0,5–2 bilhões por ano a 10^9
([05 §5](05-orcamento-e-degraus.md#5-custo-por-degrau)). Mas três coisas não são infraestrutura: (a) a lógica dos passos 1
e 3 é a própria pesquisa (L1, L2, L3); (b) a demanda (seção 2, item 1); (c) a qualidade a 10^9 (L5). Desenhar a lógica
para 10^9 é necessário, não suficiente.

### "Verificar unidade por unidade é tranquilo quando as unidades são independentes. Vira uma questão de processo e de infraestrutura."

**Verdade sobre o paralelismo, falsa sobre o custo.** Independência torna a verificação paralela: custo linear e
latência constante. Mas o custo por unidade multiplicado por 10^9 continua decidindo: a 1 s de CPU por unidade seriam
1,33 × 10^9 vCPU (~US$ 233 bilhões por ano em spot, mais do dobro do investimento anual da Microsoft [X29]). Isso não
se paga com processo nem com infraestrutura. Fica tranquilo só se a verificação cara for para a decisão (uma vez) e a
unidade só conferir o certificado (µs). Além disso, a independência precisa ser provada (L4), e propriedades do sistema
inteiro não se compõem unidade por unidade (por isso existe o V3).

### "E se o gate fosse de microssegundos (10^-6 s)?"

**Possível, e necessário, mas só como conferência.** Um gate de 1 µs a 10^9/s ocupa ~1,3 × 10^3 núcleos, e o piso físico
(0,22–0,26 ns por ciclo) permite isso para uma conferência de 10^3 a 10^4 instruções sobre dados em memória
([05 §3](05-orcamento-e-degraus.md#3-e-se-o-gate-fosse-de-microssegundos)). Um gate de µs não compila nem testa: nenhum
processo, VM, contêiner ou ida e volta de rede por PR cabe nesse tempo. O gate de µs é consequência de decisões que
chegam certificadas, não substituto da verificação. A verificação inteira do passo 3 continua precisando de ~1,8 × 10^6
vCPU, quase todos na certificação e nas amostras por decisão.

## 4. O que o próximo projeto herda

Desta arquitetura a fase 2 (a inovação) recebe: o contrato de [06](06-contrato-planejador.md) com as metas por degrau,
o placar que mede o planejador de fora, e as lacunas L1, L2, L5, L6 e as perguntas da seção 2 como o que só ela pode
responder. A primeira prova barata do contrato é no degrau 1/s: um planejador com A ≥ 10, certificado da classe
"testes de propriedade e amostra", ledger num banco e o forge como espelho; ali A, T_d e tokens por PR mergeada já são
medidos com o mesmo instrumento que vale para 10^9.
