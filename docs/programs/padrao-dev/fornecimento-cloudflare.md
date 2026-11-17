# Fornecimento: o que ainda depende da Cloudflare (17/11)

A preocupação de Daniel, recebida pela Torre às 17:36 BRT: por que ainda usamos a Cloudflare, se a decisão foi ficar só
na AWS? Esta é a análise pelo sistema Fornecimento (D-320). **Nada migra antes da decisão do dono.**

## O que depende dela, objeto por objeto
O fornecedor é o `SUP-cloudflare`, e cada dependência é um objeto do modelo:

| Dependência | Objeto | Onde está (prova) | Estado hoje | Custo de manter | Risco de manter |
|---|---|---|---|---|---|
| **Bucket de mídias** do site (`media.openuniversity.si`) | `DATA-r2-media` | `apps/web/src/media/server/r2.ts` (cliente S3, `aws4fetch`); `MEDIA_PUBLIC_HOST` em `apps/web/src/media/domain/types.ts` | ativo, serve todas as capas e mídias; **sem segunda cópia** (`unprotected`, `RISK-media-no-backup`) | R2: US$ 0,015/GB-mês de armazenamento, saída grátis, 10 GB grátis `[busca]` | perda das mídias por apagamento, falha do fornecedor ou chave de escrita vazada; único ponto fora da AWS no caminho de cada página |
| **Bucket de fidelidade** | `DATA-r2-fidelity` | `apps/web/fidelity/` | refeito pelas fontes (`regenerable`) | pequeno | baixo: refaz-se |
| **Worker `forge-webhook`** (o plano de controle, com um Durable Object) | DEP do motor, componente do `ARC-deploy` | `services/control-plane/wrangler.toml`; `service.control_url` | **parado desde a D-314**: servia os webhooks do Origin ao gate da AWS, também parado. O deployer não o publica mais (`infra/aws/deploy.sh`, GATE-SHUTDOWN) | plano grátis (`service.free_rows_read_day`) | um token de API da Cloudflare e a chave de assinatura que ele guardava continuam válidos para um serviço que nada usa (`infra/service/tower_infra/checks.py`) |
| **DNS** do domínio (e o domínio personalizado das mídias) | ASSET (o domínio) e configuração do ambiente (os registros) | inferido: um domínio personalizado no R2 pede o DNS na Cloudflare. **O repositório não registra onde está o DNS nem o registrador de `openuniversity.si`**, e isso é uma lacuna do próprio Fornecimento | desconhecido no repositório | o DNS da Cloudflare é grátis; uma zona no Route 53 custa US$ 0,50/mês mais as consultas `[conhecimento]` | um segundo painel de DNS fora da AWS; não saber onde está é, por si, um risco |
| **Credenciais** | CRED (o tipo ainda não está no modelo) | `R2_ACCESS_KEY_ID_RW`/`_RO` e os segredos (no Lambda e nas sessões), o token de API do deploy do Worker (`service.deploy_token_env`) | ativas | — | cada credencial viva é superfície de vazamento; a de escrita do R2 apaga as mídias |

## O que muda se tudo for para a AWS
- **As mídias passam para o S3 com o CloudFront na frente.**
  - **Código:** o cliente do site já é S3-compatível, então a mudança é de endpoint, de credenciais e do host público, mais o certificado no ACM.
  - **Custo:**
    - armazenamento no S3 a cerca de US$ 0,023/GB-mês `[conhecimento]`, contra US$ 0,015 no R2;
    - saída pelo CloudFront grátis até 1 TB e 10 milhões de requisições por mês, sem prazo `[busca]`. Acima disso, cobra por GB, enquanto no R2 a saída é sempre grátis.
  - **O que não sei:** o tamanho do bucket nem o tráfego mensal das mídias. Não estão no repositório, e sem eles o custo exato não se fecha. A regra é: até 1 TB por mês de saída, o custo total é o armazenamento.
  - **Bônus:** o versionamento do S3 fecha o `RISK-media-no-backup` sem um segundo fornecedor.
- **O DNS passa para o Route 53**, numa zona hospedada. Não confirmei se o `.si` pode ser registrado no Route 53. Se não puder, o registro fica no registrador atual e só o DNS muda.
- **O Worker é aposentado:** o código de `services/control-plane` sai, e o token e a chave são revogados pelo dono. Não há custo nem migração, porque nada o usa.
- **Do lado da Cloudflare, sobra:** nada, se o domínio não estiver registrado nela.

## Recomendação
1. **Aposentar o Worker já**, sem esperar o resto. Ele está parado desde a D-314, e manter o token e a chave vivos é risco sem
   benefício. A parte da sessão é tirar o código do serviço e o registro dele. A do dono é revogar o token da API e
   apagar o Worker e o Durable Object na conta.
2. **Levar as mídias para o S3 com CloudFront, com o versionamento ligado.** Isso alinha com a decisão de ficar na AWS,
   fecha o risco de backup e tira o único fornecedor fora da AWS do caminho de cada página. Pela regra acima, o custo
   fica no armazenamento enquanto a saída couber em 1 TB por mês. A ordem é:
   - copiar o bucket para o S3 e manter o R2 só para leitura durante a troca, como segunda cópia;
   - trocar o host público;
   - apagar o R2 e revogar as chaves R2 depois de 30 dias sem leitura.
3. **Registrar onde estão o domínio e o DNS** como ASSET do Fornecimento antes de mudar qualquer coisa, e então levar o
   DNS para o Route 53.
4. **O bucket de fidelidade:** apagar, ou mover junto com as mídias, porque se refaz.

Decisões do dono antes de qualquer passo:
- o custo das mídias com o tamanho e o tráfego reais;
- a revogação das credenciais da Cloudflare;
- o domínio.
