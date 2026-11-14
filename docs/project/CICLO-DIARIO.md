# Ciclo diário (v02 em diante)

Decisão do Daniel, 09/10/2026: único usuário, objetivo de **1 versão por dia** (v01 de 100). Sem fases numeradas, sem portões, sem relatórios.

## Fluxo
1. **Daniel descreve a mudança.** Se for visual, ajusta o Figma antes; protótipo e site andam juntos.
2. **Uma sessão curta do Claude** implementa em **uma branch** (`vNN/<nome>`), com **uma PR por mudança**.
3. **Gate local completo**: `scripts/gate-local --pr <n>`; inclui banco Neon descartável `pr-<n>` criado de prod, migrations e aceite por health/doctor, além da suíte local. Sem GitHub Actions.
4. **Entrega verificada**: `scripts/ship-verify <pr>` captura o antes, chama `scripts/merge-phase`, espera o deploy e verifica commit, paridade HTML e doctor em prod; apaga o banco da PR.
5. **Rollback automático** por `vercel promote` do deploy anterior se a entrega falhar. Fechar sem merge: `scripts/neon-pr close <pr>`. Limites e custos autorizados: [ADR-29](../adr/ADR-29-disposable-pr-databases-and-verified-delivery.md).

## Mantém
- **Zero dívida:** nenhum valor fora dos tokens; nenhuma supressão de lint.
- **Uma PR por mudança**, sem push direto na `main`.
- Segredos nunca impressos; nenhuma imagem de capa no git (só logo e ícones de UI).
- **Operação rotineira de mídia = API/CLI `tower-media`** (put, list, rollback, delete, check; ver `docs/media/README.md`).
- **Operação rotineira do catálogo = CLI `tower-catalog`** sobre a API admin (import, texts, review, approve, publish, `release activate`, doctor, snapshot; ver `docs/catalog/cli.md`).
- Precisou de banco/R2 direto? Foi emergência: crie o comando na API/CLI antes de repetir.

## Depois do deploy de produção
- **Metas da Home** (lab, Lighthouse mobile simulado e desktop 1440; [ADR-23](../adr/ADR-23-home-perf-budget.md)): LCP ≤ 2,5 s, CLS ≤ 0,03, TBT ≤ 100 ms, ≤ 1 MiB transferido até a 2ª linha de cards + hero. Valem para 24 e 50 cursos: o que a Home baixa antes de rolar não cresce com o catálogo. Situação em 14/10/2026 (E8, prod): desktop cumpre tudo (LCP 0,84 s); mobile cumpre CLS 0, TBT 54 ms e bytes (≈ 0,47 MiB), mas **LCP 3,54 s não cumpre** (ver ADR-23).
- **Como o orçamento é checado.** Na CI enxuta (unit, sem rede, sem Lighthouse): `scripts/lib/perf-budget-home.test.ts` renderiza a Home do snapshot (`fake.ts`) com 24 e 50 cursos e falha se um poster tiver `src` fora das `EAGER_ROWS` primeiras linhas, mais de `EAGER_CARDS_IN_HTML` por linha, preload de poster, ou se hero + posters eager × orçamento de mídia (`src/media/budget.ts`) passar de 1 MiB. Mídia: `Cache-Control: public, max-age=31536000, immutable` gravado no upload R2 (teste em `scripts/lib/r2.test.ts`) e `preconnect` ao host do hero (o LCP). Depois do deploy, o mesmo exame do HTML e os bytes reais:
- `pnpm perf:budget` (em `apps/web`; padrão `https://openuniversity.si/`, ou passe a URL): bytes transferidos do que o HTML da Home manda baixar em 390 e 1440 px, mais a auditoria de posters acima no HTML servido. Falha se total ≥ 1 MiB, imagem ≥ 120 KiB, fonte ≥ 60 KiB, mais de um download de hero ou poster sob demanda fora do lugar. Preview protegida: exporte `VERCEL_AUTOMATION_BYPASS_SECRET`. LCP/CLS/TBT medidos pelo executor (Lighthouse, fora da CI); números no ADR-23.
- Mudou mídia? `tower-media check --target prod --budget` (ADR-15). Lighthouse fica fora da CI (pesado).

## Não existe mais
Fases F01–F15 como fila, `-done.md`, `fidelity` no portão, ensaios de rollback, revisão final, observação de 7 dias, jobs agendados (`nightly.yml` e `mux-check.yml` só manuais).
