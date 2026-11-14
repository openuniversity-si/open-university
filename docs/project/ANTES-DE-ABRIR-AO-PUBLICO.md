# Antes de abrir ao público (lista sem prazo)

Nada daqui é exigido enquanto o Daniel for o único usuário. Fazer só quando houver decisão de abrir o site.

- [ ] **CSP e headers de segurança** (CSP com nonce em enforce, HSTS, `nosniff`, `Referrer-Policy`, `Permissions-Policy`); hoje sem enforce.
- [x] **`/privacy`, `/terms`, `/contact`**: feito (v02). Texto em `apps/web/src/site/pages/legal.ts`, fonte única; o Daniel pode ajustar o texto lá.
- [x] **`/about` e frase de valor na Home** ("Great lectures, in order. Universal, Free & Luxurious." + "About The Tower ›"): feito em 10/10/2026 (v02). Texto institucional mínimo ("we", sem nomes de autores, sem números, sem compromissos fixos) por decisão do Daniel; mesma PR deixou Privacy, Terms e a description padrão genéricas. Texto em `apps/web/src/site/pages/legal.ts` (`ABOUT_PAGE`, `HOME_INTRO`), travado por teste.
- [ ] Link para `/privacy` no menu da conta; publicar a tela de consentimento do Google ("In production").
- [ ] **Exclusão de conta** (rotina de apagar usuário, sessões e progresso).
- [x] **`robots` / noindex**: feito em 10/10/2026 (v02, ADR-12): produção indexável por `VERCEL_ENV`, previews noindex, sitemap em `/sitemap.xml`.
- [x] **Favicon, título, description, Open Graph, canonical e manifest**: feito em 10/10/2026 (v02, ADR-13). Fonte única em `apps/web/src/site/metadata.ts`; rotas públicas em `apps/web/src/site/routes.ts`.
- [x] **Performance: Home estática**: feito em 10/10/2026 (v02, ADR-16). Visitante recebe `/` do cache da Vercel (ISR, 300 s + revalidação por mídia); logado é reescrito para a rota dinâmica privada.
- [ ] **Monitor de uptime** (e rota `/api/health` observada).
- [ ] **Custo do Mux:** estimativa e alerta em **US$ 20 e US$ 25** (sem rotina diária por enquanto).
- [ ] **Ensaio de rollback** (Instant Rollback da Vercel, cronometrado).
- [ ] **Revisão final** do Daniel com roteiro curto.
- [ ] **Observação** pós-abertura (período a definir).
- [ ] **Desativar o legado** (branch/tag `legacy`, deploys antigos) depois de estável.
