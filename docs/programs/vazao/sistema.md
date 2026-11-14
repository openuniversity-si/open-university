# VAZÃO: o sistema, as restrições e o caminho (versão 1, 03/11/2026)

Quatro perguntas (Daniel, 03/11): qual é o sistema de hoje e onde ele trava, o que o mundo sabe, qual sistema miramos e
como migrar. Complementa o [programa](programa.md) (avaliação, solução A2, fases) com o mapa de restrições medido. Cada
número tem fonte; o que é estimativa está marcado. Revise este documento a cada degrau ou quando a restrição mudar.

## 1. O sistema de hoje e as suas restrições

Fluxo de uma PR: a lane escreve 1 a 8 commits no seu worktree → cada push roda o pre-push (5 a 27 s) → abre a PR no
Origin → `scripts/deliver` traz a base, roda o gate no head exato, julga de novo se a base andou (até 3 rodadas) e faz
o merge com `--expect-head`. O trem (fila de merge em lote) está parado.

| Recurso | Capacidade (teto) | Uso observado em 03/11 | Fonte |
|---|---|---|---|
| Unidades prontas e independentes (fila) | o que a fila tiver | 0 linhas livres depois de F16/F17; o lote anterior era uma cadeia (F8 → F9 → F15 → F17) | `docs/programs/vazao/fila.md` |
| Lanes (escrita pelo modelo) | 2 simultâneas (regra I-2012f37d) | 8 PRs em 71 min com 1 a 2 frentes: 6,8 PR/h, 0,0019 PR/s | `scripts/usage --tokens --per-pr` sobre a transcrição da sessão |
| CPU da caixa de verificação (4 CPUs) | uma suíte por vez: 113 s sozinha; 3 simultâneas levam 346 s cada (ganho zero) | gate head→merge em 84 merges: p25 87 s, mediana 105 s, p75 153 s | medição desta sessão; `git log` dos merges de 03/11 |
| Teto da caixa para o gate | 3.600 s ÷ 105 s ≈ 34 PR/h ≈ **0,0095 PR/s** | — | derivado das duas linhas acima |
| Ponto de merge (base que anda) | sem lote, cada PR é julgada sozinha | #79 julgada 2 vezes porque #78 entrou durante o gate | saída do `deliver` |
| Gate vermelho e re-julgamentos | — | 82 merges de 03/11: p = 0,133 dos gates vermelhos, n_r = 1,25 gates por merge, 6 re-julgamentos por base movida; nos últimos 10, 3 re-julgamentos contra 2 vermelhos | `scripts/flow-metrics --guards` (F24, #91) |
| Painel de controle (Worker + Durable Object) | desconhecida: erro 1101 em todas as rotas desde ~17:00 UTC de 03/11 | o diário e o armazém compartilhado de config fora; gate e merge seguem pelo git-ref (D-296) | I-5102f4e9 (#94) |
| Origin (API) | 600 requisições por janela de 60 s (10/s) | dezenas por PR (estimativa); folga de duas ordens de grandeza | cabeçalhos `x-ratelimit-*` de `origin api` |
| Cota (conta Max) | janela de 5 h e semanal; número em tokens não exposto | ~50 mil tokens não cacheados e ~14 mil de saída por PR; a janela aguentou 2 frentes (Daniel, 03/11) | `scripts/usage`; SEMENTE §6 |

**Restrição de hoje (passo 1 de Goldratt):** a oferta de unidades prontas e independentes, e com ela o número de lanes.
**A próxima:** a CPU da caixa. Com 105 s de gate por PR, uma caixa não passa de ~0,0095 PR/s, abaixo do degrau 1
(0,0116). Mais lanes na mesma caixa só deslocam a espera para o gate (Kingman: perto de 100 % de uso a espera explode).
Rodar a suíte inteira antes do `deliver` dobra o uso de CPU por PR, a menos que o gate reaproveite o resultado pela
chave de conteúdo (a verificar). E 2 das 3 suítes simultâneas tiveram uma falha sob carga: há teste sensível a tempo.

## 2. O que o mundo sabe

O [programa §2](programa.md#2-pesquisa-o-que-o-mundo-já-sabe) resume Little, Goldratt e as filas de merge. A pesquisa
aprofundada, feita por uma lane independente em 03/11, está em [docs/research/toc.md](../../research/toc.md): Teoria das
Restrições, filas (Little, Kingman), DORA, filas de merge e agentes de código em paralelo, com um guia de aplicação ao
motor (§6). O que ela muda aqui: o primeiro passo de elevação é baixar a taxa de gate vermelho (cada vermelho custa CPU,
cota e tempo de uma vez), um gate por caixa de 4 CPUs, e o limite de lanes é o menor entre cota, CPU, suprimento de
unidades e conflitos, cada um com fórmula. A segunda pesquisa, [docs/research/box.md](../../research/box.md), mostra que nenhum plano
gratuito dá uma segunda caixa útil e que o lote na caixa atual (o trem, lote ótimo 5 com p = 0,13) chega ao degrau 1.

## 3. O sistema que miramos (degrau 1: 0,0116 PR/s, 42 PRs por hora)

- **Fila com folga:** pelo menos 2 unidades independentes prontas por lane (o pulmão do Drum-Buffer-Rope), com escopos
  de arquivo disjuntos. A descoberta de unidades é um passo do ciclo, não um lote esporádico.
- **Lanes:** N tal que N × ~4 PR/h ≥ 42. Hoje isso é ~10 lanes, o que a cota provavelmente não paga. Por isso o ciclo
  por PR também precisa cair: menos releitura de contexto e PRs que já nascem verdes.
- **Verificação abaixo de 86 s de CPU por PR em média:** o gate reaproveita os testes pela chave de conteúdo, a seleção
  fica estreita, e PR só de documento custa segundos.
- **Merge em lote quando há fila:** com 2 ou mais PRs prontas, um gate julga o lote (o trem); com 1, o `deliver`.
  Pela Lei de Little, o lote paga quando a chegada × o tempo de gate passa de 1.
- **Mais de uma caixa quando a CPU for a restrição:** uma segunda caixa de verificação é dinheiro, portanto decisão
  de Daniel.

**Atualização das 19:00 UTC de 03/11.** Feito do plano abaixo: o passo 1 (fila reabastecida em lotes), o 2 (o gate
reaproveita a suíte pela chave, F19; um gate por vez na caixa, F23; a trava cobre o merge da base e o merge, F27; o
`deliver` tirou da trava o PR/s e o pre-push repetido, F33) e parte do 3 (a descoberta de unidades virou uma frente
própria). Medidas novas: vermelho p = 0,133 e n_r = 1,25 (F24); os últimos 10 merges em 1.977 s, 0,0051 PR/s (~18 por
hora); a janela de 5 h em 33 % e a semanal em 5 % com três frentes. A restrição continua sendo a oferta de unidades; a
seguinte, a caixa em série: o gate leva ~50 s numa PR só de documento e ~100 s numa de código, então a caixa sozinha não
passa de ~36 a 70 PRs por hora. A cota tem folga, e a folga vai para frentes que não passam pelo gate (até cinco, no
máximo três no gate). O painel de controle caiu às 16:58 UTC por estourar o plano gratuito (I-5102f4e9); com F28 e F35
ele volta a caber, e a regra "cabe no plano gratuito com folga" entrou no SEMENTE §4.

## 4. Migração (cada passo começa medindo e termina verificando)

1. **Agora: lanes de 2 para 3** (eu, que coordeno e meço, mais 2 subagentes), com a fila reabastecida por unidades
   independentes. Medir a cada hora a vazão, o uso de CPU (re-julgamentos e tempo de gate) e os tokens por hora. Voltar
   para 2 se a mediana do gate passar de 150 s ou se a janela de 5 h apertar.
2. **Verificação mais barata por PR:** confirmar se o gate reaproveita a suíte pré-entrega pela chave de conteúdo. Se
   não reaproveitar, a lane roda só o gate. Depois, medir a CPU por estágio do gate e cortar o maior. Achar e corrigir os
   testes que falham sob carga.
3. **Descoberta de unidades como rotina:** a cada ciclo, o coordenador mede (`covers-cost`, tamanho das unidades,
   módulos sem leitor, defeitos) e escreve linhas novas na fila antes que ela seque. A linha entregue sai em lote, pelo
   coordenador, para que N lanes não se choquem na mesma tabela.
4. **Merge em lote:** religar o trem na caixa (sem a VM) quando a chegada × o gate passar de 1 de forma sustentada,
   medido pelos re-julgamentos do `deliver`.
5. **Segunda caixa:** só quando os passos 2 a 4 estiverem feitos e a CPU continuar sendo a restrição (precisa de Daniel).
