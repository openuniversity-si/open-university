# 05. Orçamento de limites e custo por degrau

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

Entregável 4. Onde está cada gargalo, com a conta; o custo de cada degrau de 1/min a 10^9/s; o que muda de um degrau para
o outro sem refazer a arquitetura; e o julgamento dos dados T4 a T9 da Torre. As contas são [I] sobre as fontes
citadas e foram feitas com um script de ~60 linhas fora do repositório; as fórmulas e todos os parâmetros estão aqui,
para que qualquer número possa ser refeito à mão.

## 1. Os preços e as taxas que entram na conta

| Parâmetro | Valor | Fonte |
|---|---|---|
| vCPU·h spot | US$ 0,0199 (GCP c4d-standard-384, Iowa) | [X26] |
| vCPU·h sob demanda | US$ 0,0449 (AWS m8g, us-east-1) | [X25] |
| GPU·h spot | B200 US$ 4,95; H100 US$ 6,0–6,6 | [A8] |
| Tokens por GPU, frota real | ~4.950 tokens/s por H800, entrada e saída somadas | [A1, I] |
| Custo de token em frota própria | ~US$ 0,11 por milhão a US$ 2/GPU·h; o mesmo com B200 spot, que vale 2,53 H100-equivalentes | [A1, A16, A8, I] |
| Token por API, mistura de agente (~94 % leitura de cache) | Haiku 5.5 ~US$ 0,018/M; Sonnet 5.5 ~US$ 0,275/M; Opus 5.5 ~US$ 0,55/M; lote: metade | [A5, A9, I] |
| Armazenamento de objetos | US$ 0,021–0,023 por GB·mês | [X27] |
| Rede entre regiões | US$ 0,02 por GB (usado como teto para réplica entre domínios de falha) | [X28] |
| Tokens servidos pelo Google | ~1,22 × 10^9 por segundo (mai/2026) | [A14, I] |
| Tokens servidos no mundo | ~5–8 × 10^9 por segundo (nov/2026) supondo o Google com 30–50 % do total e o volume dobrando de mai a nov | [E] |
| Teto de hardware de inferência | ~7,2 × 10^10 tokens/s: 29,1 milhões de H100-equivalentes × 50 % em inferência × 4.950 tokens/s | [A16, A1, E] |
| Tokens por PR feita por agente | 10^5 a 10^7, central 10^6 (inclui leitura de cache) | [A10, A11, A13, I] |

## 2. O gargalo de cada passo, com a conta

| Passo | Recurso que limita | Conta a 10^9 | Resultado | Teto se a premissa falhar |
|---|---|---|---|---|
| 1. Decidir | tokens de IA | D × T_d = 10^3 × 10^5 + exceções do passo 2 (10^9 × 10^-5 × 10^3) = 1,1 × 10^8 tokens/s; ÷ 4.950 ÷ 0,75 | ~3 × 10^4 H100-equivalentes | com IA PR a PR (A = 1) seriam 10^15 tokens/s, ~1,4 × 10^4 vezes o teto de hardware do mundo |
| 2. Gerar | núcleos do motor de transformação | 1,5 × 10^9 instâncias/s × 10 µs | 1,5 × 10^4 vCPU | a 86 µs por instância (parse incluso [V36]) seriam 1,3 × 10^5 |
| 3. Verificar | núcleos da verificação por decisão | 1,33 × 10^3 decisões/s × 10^3 núcleo·s, mais V0, V1 e 25 % de V3 | ~1,8 × 10^6 vCPU | a 1 s de verificação por PR seriam 1,33 × 10^9 vCPU, ~US$ 233 bi/ano em spot, mais do dobro do investimento anual da Microsoft [X29] |
| 4. Gravar | bytes do ledger | 10^9 × 128 B | 128 GB/s (170 com folga), ~10^3 brokers | um commit por PR num ref só: o git aceita um escritor por vez por repositório [S18]; o Google faz ~0,75 commit/s num repositório [S2] |
| 5. Coordenar | transições de workflow | 10^3 decisões/s × 50 transições | 5 × 10^4/s (~0,5 do Cadence da Uber [C24]) | um workflow por PR seriam 10^9 novos/s, 10^4 vezes o maior parque publicado |

**O gargalo real é o passo 1**, e ele só fecha porque a decisão é amplificada. O segundo gargalo é a verificação por
decisão, não o gate por PR.

## 3. E se o gate fosse de microssegundos?

A pergunta de Daniel. A tabela dá o custo de cada operação por PR a 10^9 PRs/s: o tempo vezes 10^9 é o número de
núcleos ocupados (se a operação usa CPU) ou de PRs em voo (se é espera), antes da folga de ρ = 0,75.

| Operação por PR | Tempo | 10^9 × tempo | Fonte |
|---|---|---|---|
| leitura em cache L1 | 0,5 ns | ~1 núcleo | [X21] |
| leitura de memória ou chamada de sistema | 100 ns | 100 núcleos | [X21, X22] |
| troca de contexto | 1 µs | 10^3 núcleos | [X22] |
| ida e volta de RPC rápido no datacenter (eRPC) | 2,3 µs | 2,3 × 10^3 em voo | [X23] |
| criar uma thread | 50 µs | 5 × 10^4 núcleos | [X22] |
| ida e volta na mesma zona | 100 µs | 10^5 em voo | [X22] |
| criar um processo | 300 µs | 3 × 10^5 núcleos | [X22] |
| hash de um diff de 1 MiB a 1 GiB/s | 1 ms | 10^6 núcleos | [I] |
| subir o gerenciador de uma microVM | 8 ms de CPU | 8 × 10^6 núcleos | [X1] |
| boot de microVM | 125 ms | 1,25 × 10^8 em voo; a 150 por segundo por host, 6,7 × 10^6 hosts | [X1, X2] |
| subir um contêiner | ~1,1 s | 1,1 × 10^9 em voo | [X7] |

Conclusões:

1. **O piso físico está entre ns e µs, como a Torre estimou (T9).** Um ciclo de CPU de servidor a 3,9–4,5 GHz [X25]
   dura 0,22 a 0,26 ns. Uma conferência que cabe em ~10^3 a 10^4 instruções sobre dados já em memória leva 0,3 a 3 µs.
2. **Um gate de 1 µs é possível só como conferência em processo**, com os dados já na memória da célula, em lote (sem
   uma chamada de sistema por PR) e sem rede por PR. É o V0. Compilar, testar, subir processo, VM ou contêiner por PR
   está fora de alcance a 10^9, qualquer que seja o dinheiro.
3. **Um gate de µs não basta.** Ele confere o que a certificação provou; o custo da verificação vai para a decisão
   (10^3 núcleo·s cada, 1,8 × 10^6 vCPU no total). A tese "verificar uma vez, conferir em µs" é a mesma do código que
   carrega a prova [V27], e o único caso publicado em produção é o Alive no LLVM [V19].

## 4. A IA: capacidade do mundo e a amplificação que fecha a conta

- **Com IA PR a PR (A = 1)**, o mundo inteiro, sem fazer mais nada, faria ~5 × 10^3 PRs/s com os tokens servidos hoje
  (5 × 10^9 ÷ 10^6) e ~7 × 10^4 PRs/s no teto de hardware (7,2 × 10^10 ÷ 10^6) [I]. Hoje se observam ~42 PRs/s
  iniciadas por agentes no GitHub inteiro (110 milhões em set/2026) [S17, I] e ~9,9 PRs públicas mergeadas por segundo
  no total [X31].
- **A conta da amplificação.** Com orçamento de tokens B_t, tokens por decisão T_d e vazão λ:
  A ≥ λ × T_d ÷ B_t, ou seja, **tokens de IA por PR mergeada = T_d ÷ A ≤ B_t ÷ λ**.
- **O orçamento escolhido** é B_t ≈ 1,5 × 10^8 tokens/s (RNF-04 e 01 §5): ~2–3 % dos tokens servidos no mundo [E], ou
  ~12 % do volume do Google de mai/2026 [A14]. Isso dá **≤ 0,15 token de IA por PR mergeada**. O motor hoje gasta
  ~10^6 por PR ([02](02-estado-atual.md)): a redução exigida é de ~7 × 10^6 vezes.
- **Duas formas de cumprir:** A ≥ 10^6 com T_d ≤ 10^5 (a meta de projeto), ou A ≥ 10^7 com T_d ≈ 10^6 (a mediana de uma
  tarefa de agente hoje [A10, A11]).

| Amplificação A | Decisões/s a 10^9 | Tokens/s com T_d = 10^5 | Fração do teto de hardware do mundo | Cabe no orçamento? |
|---|---|---|---|---|
| 1 | 10^9 | 10^14 (com T = 10^6 por PR: 10^15) | 1.400× | não |
| 10^4 | 10^5 | 10^10 | 14 % | não |
| 10^5 | 10^4 | 10^9 | 1,4 % (o volume inteiro do Google em mai/2026) | não |
| **10^6** | **10^3** | **10^8** | **0,14 %** | **sim** |
| 10^7 | 10^2 | 10^7 | 0,014 % | sim, com folga para T_d = 10^6 |

## 5. Custo por degrau

A mesma arquitetura em todos os degraus; mudam a amplificação, o número de partições e células, e os adaptadores das
portas ([03 §5](03-arquitetura.md#5-portas-e-adaptadores)). Parâmetros: verificação por decisão de 10^3 núcleo·s (no
degrau A = 1, o gate de hoje, ~450 núcleo·s por PR: 105 s em 4 CPUs [M]); V0 de 1 µs, V1 de 1 ms em 1 % das
instâncias, V3 com 25 % do total da verificação; registro de 128 B por PR; 200 B quentes por PR por 7 dias.

| Degrau | A | Decisões/s | T_d | Tokens/s | Verificação (vCPU) | Ledger | Partições e células |
|---|---|---|---|---|---|---|---|
| 1/min | 1 | 0,0167 | 10^6 por PR | 1,7 × 10^4 | 10 | o forge | 1 partição |
| 1/s | 10 | 0,1 | 10^6 | 10^5 | 180 | git próprio + ledger num banco | 1 a 4 partições |
| 10^3/s | 10^3 | 1 | 10^6 | 10^6 | 1,8 × 10^3 | 0,13 MB/s | ~10 partições, 1 célula |
| 10^6/s | 10^5 | 10 | 3 × 10^5 | 3 × 10^6 | 1,8 × 10^4 | 128 MB/s, ~10 brokers | 10^2–10^3 partições, 1 a 10 células |
| 10^9/s | 10^6 | 10^3 | 10^5 | 1,1 × 10^8 | 1,8 × 10^6 | 128 GB/s, ~10^3 brokers | ≥ 10^4 partições, ≥ 10^3 células |

| Degrau | IA por API, Haiku 5.5 a Sonnet 5.5 | IA em frota própria | Verificação (spot) | Resto (ledger, metadados, rede, armazenamento) | Total por ano | Por PR |
|---|---|---|---|---|---|---|
| 1/min | US$ 9,5 mil a 145 mil/ano, ou dentro da cota da conta Max | não compensa (menos de um nó) | ~US$ 2 mil/ano, ou a caixa grátis com o cache do gate | planos gratuitos | **≤ US$ 0,15 milhão** | ≤ US$ 0,28 |
| 1/s | US$ 57 mil a 0,87 milhão/ano | não compensa | ~US$ 31 mil/ano | um servidor de git, um banco e trabalhadores: dezenas de vCPU | **~US$ 0,1–0,9 milhão** | US$ 0,003–0,03 |
| 10^3/s | US$ 0,57 a 8,7 milhões/ano | ~US$ 3,5 milhões/ano (~270 H100e) | ~US$ 0,3 milhão/ano | pequeno | **~US$ 1–9 milhões** | US$ 3 × 10^-5–3 × 10^-4 |
| 10^6/s | US$ 1,7 a 26 milhões/ano | ~US$ 11 milhões/ano (~810 H100e) | ~US$ 3,1 milhões/ano | ~US$ 1 milhão/ano | **~US$ 6–30 milhões** | US$ 2 × 10^-7–10^-6 |
| 10^9/s | US$ 62 milhões a 0,95 bilhão/ano | ~US$ 0,39–0,51 bilhão/ano (~3 × 10^4 H100e; 1,2 × 10^4 B200 spot) | ~US$ 0,31 bilhão/ano (0,71 sob demanda) | ~US$ 0,16–0,25 bilhão/ano: réplica entre domínios (128 GB/s × 2 × US$ 0,01–0,02/GB [E para o valor dentro da região]), 120 PB quentes (~US$ 30 milhões/ano), ~3 × 10^5 vCPU dos outros componentes (~US$ 50 milhões/ano) | **~US$ 0,5–2 bilhões** | **US$ 1,7–6 × 10^-8** |

A 10^9 o custo por PR fica entre 1,7 e 6 × 10^-8 dólar, dentro da meta de 10^-7 (RNF-04). Em ordem de grandeza, a
fábrica a 10^9 custa o que custa uma frota de nuvem de porte médio por ano; a energia é ~32 a 40 MW (GPUs com ~0,6 kW
de potência de chip por H100-equivalente [A16], vCPU a ~4 W [E], sobrecarga do prédio de 1,2 a 1,5× [E]), ou ~0,03 a
0,04 J por PR, dentro de RNF-10.

## 6. O que muda de um degrau para o outro

Nenhum componente entra ou sai. Mudam parâmetros e adaptadores:

| Passagem | Parâmetro que muda | Adaptador que troca | Por que nesse degrau |
|---|---|---|---|
| hoje → 1/min | o gate com o cache por conteúdo (0,99 s em vez de 105 s) ou 3 caixas; ~4× as frentes de hoje | nenhum | a 105 s por PR uma caixa não passa de ~34 PRs/h [M] |
| 1/min → 1/s | A ≥ 10: o planejador começa a emitir decisões com vários lugares | registro: do merge no forge para git próprio com ledger num banco; o forge vira espelho de PRs de decisão, com token de instalação | o forge não passa de ~0,8 PR/s nem com o JWT de app, com a folga de 50 % ([02](02-estado-atual.md)); a maior taxa de commits publicada num repositório só é ~0,75/s [S2] |
| 1/s → 10^3/s | A ≥ 10^3; certificado por decisão; V0 por instância; ~10 partições | registro: ledger particionado; workflow: motor durável; escalonador de cluster | com o gate de hoje (~450 núcleo·s por PR) 10^3 PRs/s pediriam 6 × 10^5 vCPU; com cache e build incremental (~10 núcleo·s) 1,3 × 10^4; certificando a decisão, ~1,8 × 10^3, e esse custo não cresce com A |
| 10^3/s → 10^6/s | A ≥ 10^5; 10^2–10^3 partições; células | inferência: frota própria passa a competir com a API; ledger num log particionado | o custo de IA domina; com ~10^2–10^3 GPUs a frota própria fica mais barata que a API dos modelos médios (os pequenos por API seguem mais baratos por token), e a escolha passa a ser de qualidade e de capacidade contratável |
| 10^6/s → 10^9/s | A ≥ 10^6 e T_d ≤ 10^5; ≥ 10^4 partições; ≥ 10^3 células | despacho por puxada em toda célula; claims locais por célula; log de transparência por snapshot | sem isso os tokens passam do orçamento (seção 4) e os workflows e claims passam dos maiores parques publicados |

**Onde o plano gratuito deixa de caber** (RNF-12, a regra da semente §4): em 1/min ainda cabe, se o gate usar o cache
(uma caixa basta) e a IA couber na cota da conta Max (com três frentes a janela de 5 h ficou em 33 % e a semana em 5 %,
AGENTS.md); a partir de ~0,1 PR/s a cota do usuário no Origin passa de 50 % e, em 1/s, nenhum plano gratuito cobre o
registro e a IA. Daí para cima o custo é o da tabela acima: é a entrada da fase 3, buscar dinheiro.

## 7. Sensibilidade a 10^9

A meta de custo (≤ 10^-7 por PR) quebra se qualquer destas premissas falhar:

| Premissa | Se falhar | Custo a 10^9 |
|---|---|---|
| T_d ≤ 10^5 com A = 10^6 | T_d = 10^6 | IA de ~US$ 110–280/s (frota própria a Sonnet 5.5); ~US$ 3,5–9 bilhões/ano; 1,1–2,8 × 10^-7 por PR só de IA |
| A ≥ 10^6 | A = 10^5 (10^4 decisões/s) | 10^9 tokens/s, o volume inteiro do Google em mai/2026; ~US$ 3,6–4,6 bilhões/ano só de IA em frota própria |
| ≤ 10^3 núcleo·s de verificação por decisão | 10^4 núcleo·s | 1,8 × 10^7 vCPU, ~US$ 3 bilhões/ano spot, 10^-7 por PR só nisso |
| nenhum processo, VM ou rede por PR | 300 µs por PR (um processo) | +4 × 10^5 vCPU, ~US$ 70 milhões/ano; o boot de uma VM por PR é impossível (seção 3) |

**As três alavancas, em ordem:** a amplificação A, os tokens por decisão T_d e o custo de certificar uma decisão.
Preço por token e preço de CPU entram linearmente; as três alavancas entram como divisores. É o que o contrato do
planejador fixa em [06](06-contrato-planejador.md).

## 8. Os dados da Torre T4 a T9

| # | Dado | Veredito | Por quê |
|---|---|---|---|
| T4 | Escrita em lote com fonte de verdade distribuída: 10^6–10^7/s | **confirmado, e o teto é maior** | anexos em lote de 128 B a 10^9/s são 128 GB/s, ~1 % da ingestão do Scribe da Meta (mais de 15 TB/s [C11]); o DynamoDB chegou a 1,92 × 10^8 requisições/s [C18]. O limite está em transação consistente por PR (dezenas de milhares por segundo por cluster FoundationDB [S22]), que a arquitetura não usa |
| T5 | Verificação incremental com cache, paralela: ~10^6/s ao custo de uma região | **confirmado na ordem, e evitado** | a ~1 núcleo·s por PR, 10^6/s são 1,33 × 10^6 vCPU, ~US$ 233 milhões/ano em spot [I]; com a certificação por decisão, 10^6/s custam ~1,8 × 10^4 vCPU, ~75 vezes menos |
| T6 | Gate de 1 µs: ~10^3 núcleos para 10^9/s | **confirmado para o V0, insuficiente para o passo** | 10^9 × 1 µs ÷ 0,75 = 1,3 × 10^3 núcleos; mas a verificação inteira pede ~1,8 × 10^6 vCPU, porque a certificação e as amostras por decisão dominam |
| T7 | Geração por IA PR a PR: ~10^4–10^5/s no mundo todo | **confirmado como teto de hardware** | ~7 × 10^4 no teto de hardware; ~5 × 10^3 com os tokens que o mundo serve hoje; observado: ~42 PRs/s iniciadas por agentes no GitHub [S17] |
| T8 | 10^9 só fecha se cada decisão virar ~10^5–10^6 PRs | **confirmado e apertado** | com toda a inferência do mundo bastaria 10^4–10^5; com o orçamento que cabe na meta de custo, A ≥ 10^6 (T_d ≤ 10^5) ou A ≥ 10^7 (T_d ≈ 10^6) |
| T9 | Um ciclo de clock é ~200–300 ps; o piso do gate fica entre ns e µs | **confirmado** | 3,9–4,5 GHz [X25] dão 0,22–0,26 ns por ciclo; L1 0,5 ns, memória 100 ns [X21]; qualquer salto de rede custa ≥ 2,3 µs [X23] |

## 9. A escala de 10^9 contra o mundo

- 10^9 PRs/s são ~10^8 vezes as PRs públicas mergeadas hoje no GitHub (9,94/s em out/2026 [X31]) e ~2,4 × 10^7 vezes
  todas as PRs mergeadas no GitHub, privadas inclusive (~41/s [S17]).
- São ~12 vezes as requisições HTTP médias da Cloudflare inteira (81 milhões/s [C20]) e ~5 vezes o pico do DynamoDB no
  Prime Day 2026 [C18].
- Todo o arquivo do Software Heritage (5,95 × 10^9 commits, 29,3 × 10^9 arquivos únicos [X30]) equivale a 6 segundos
  de produção da fábrica em commits.

A infraestrutura cabe no que já foi demonstrado, com dinheiro. A pergunta que esses números deixam é outra: **onde existe
trabalho útil para 10^9 PRs por segundo**. Ela é do planejador e está em [07](07-lacunas.md).
