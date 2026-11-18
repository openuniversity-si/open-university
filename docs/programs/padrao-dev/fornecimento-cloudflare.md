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

## A decisão e a execução (17/11, D-323)
O dono aprovou a recomendação inteira às 18:20 BRT: sair de tudo da Cloudflare e ficar só na AWS (D-323).

**Os números reais**, lidos pela Torre sem mudar nada:

| Bucket | Objetos | Tamanho | Domínio |
|---|---|---|---|
| `open-university-media` | 31.026 | 3,388 GB | `media.openuniversity.si` |
| `the-tower-fidelity` | 1.178 | 1,212 GB | — |
| `the-tower-media` (legado) | 1.329 | 0,180 GB | nenhum |

- **Total:** 4,78 GB.
- **Leitura na origem em 30 dias:** 21.373 GetObject (2,459 GB) e 81.462 HeadObject.
- **DNS:** a zona `openuniversity.si` está na Cloudflare. O `media` é um CNAME com proxy para o R2, e o apex e o `www` já apontam, sem proxy, para o CloudFront.
- **Domínio:** o registrador é a OpusDNS, revenda da Hostinger, e o registro expira em 11/10/2027. O `.si` não se registra nem se transfere no Route 53, então só o DNS muda: uma zona no Route 53, e a troca dos NS no registrador.

**O custo na AWS**, com esse tráfego:
- **S3:** 4,78 GB, cerca de US$ 0,11 por mês.
- **CloudFront:** dentro do 1 TB grátis.
- **Route 53:** US$ 0,50 por mês pela zona, mais as consultas.
- **Total:** cerca de **US$ 0,65 por mês**, contra US$ 0 hoje, porque o R2 ainda cabe nos 10 GB grátis.

**Os passos:**
1. **O Worker, aposentado** (esta PR):
   - saíram o código, a unidade, o teste, o `service_deploy.py` e as chaves que só ele lia;
   - o executor da era Origin continua dormente, e o job `DEPLOY` dele falha com o motivo da D-323;
   - na conta não há o que apagar, porque o Worker e o Durable Object já não existiam.
2. **As mídias para o S3:**
   - uma stack com o bucket (versionamento ligado) e o CloudFront; o certificado do ACM é pedido fora dela (ver "Passo 2: execução");
   - a cópia do bucket, com o R2 só para leitura como segunda cópia durante a troca;
   - a troca do host público;
   - o R2 apagado depois de 30 dias sem leitura (passo da Torre).
3. **O DNS:**
   - o domínio registrado como ASSET;
   - a zona no Route 53, replicando todos os registros atuais, inclusive e-mail, verificações e o CNAME novo das mídias;
   - a troca dos NS no registrador (passo da Torre).
4. **No fim, todas as credenciais da Cloudflare revogadas** (passo da Torre).

## Passo 2: execução
**O que esta PR traz.** A stack `infra/aws/stacks/60-media.json` (`tower-app-media`, sem dependência em `order.json`):
- **`tower-media-<conta>-us-east-1`**, o bucket das mídias:
  - versionamento ligado; a versão não corrente fica 90 dias (cobre a janela de 30 dias do R2 e a demora em perceber um apagamento; como as chaves são imutáveis, quase não há versões antigas);
  - SSE-S3, todo acesso público bloqueado, `BucketOwnerEnforced`, só por TLS;
  - os dois buckets ficam retidos (`Retain`) se a stack sair.
- **`tower-media-logs-<conta>-us-east-1`**, os logs de acesso do bucket, guardados 90 dias. Custam centavos.
- **Com `Cdn=on`:**
  - uma distribuição do CloudFront com Origin Access Control (sigv4, `always`), e a política do bucket só deixa essa distribuição ler (`s3:GetObject`, `AWS:SourceArn`);
  - só HTTPS, `PriceClass_100`, sem log, WAF ou função de borda;
  - cache de um ano para as chaves imutáveis, sem query, cookie ou cabeçalho na chave;
  - o domínio padrão `*.cloudfront.net` até `CertificateArn` e `Alias` estarem os dois preenchidos.
- **Nenhum certificado nem registro de DNS dentro de stack**, para que o deploy de um merge nunca espere validação (o teste `MediaStackTests` prova isso). O certificado é pedido fora da stack.
- **O custo:** cerca de US$ 0,13 por mês, contra o limite de US$ 150 de `infra/aws/budget.json`:
  - 3,388 GB × US$ 0,023;
  - cerca de 103 mil leituras na origem por mês (21.373 GET e 81.462 HEAD) × US$ 0,0004 por mil;
  - 2,459 GB e cerca de 100 mil requisições por mês, dentro do 1 TB e dos 10 milhões grátis do CloudFront;
  - a cópia, uma vez só: 31.026 PUT, cerca de US$ 0,16.
- **O bucket de fidelidade não é copiado:** o modelo o dá como `regenerable` (o `fidelity:sync` o refaz). O harness, porém, lê o `the-tower-fidelity` no R2 (`apps/web/fidelity/references/storage.ts`). Por isso, antes do passo (f), uma PR leva esse armazenamento para um bucket privado da AWS e o `fidelity:sync` o refaz lá. Se a referência que ele fotografa não existir mais, a Torre copia o bucket como está (1,212 GB, cerca de US$ 0,03 por mês).
- **O legado `the-tower-media`** (sem domínio, sem leitor no código) não é copiado: sai com o R2 no passo (f).

**O que acontece depois, e quem faz:**
1. **(a) O deploy cria os buckets.** Faz isso sozinho, no merge desta PR: o `parameters.json` vem com `Cdn=off`. A fronteira `tower-boundary` só permite `cloudfront:*` depois que a Torre reaplica o `tower-bootstrap` com este `bootstrap.json` (com `UsePreviousValue` nos parâmetros, como na QUEUE-RELOAD; o hash está em `test_infra_aws.py`). Feito isso, uma PR põe `Cdn=on`, e o deploy cria a distribuição. As saídas `BucketName`, `DistributionId` e `DistributionDomain` da stack dão os nomes.
2. **(b) A cópia R2 → S3 (Torre).** Pede a chave R2 **só de leitura**, que nenhuma sessão pode ter, e credenciais da AWS com escrita no bucket. Roda no CloudShell em `us-east-1`, para a leitura de verificação no S3 não sair da região. As chaves ficam só em variáveis de ambiente, nunca em arquivo nem no repositório:
   ```sh
   export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
     RCLONE_CONFIG_R2_ENDPOINT=https://<conta-cloudflare>.r2.cloudflarestorage.com \
     RCLONE_CONFIG_R2_ACCESS_KEY_ID=<chave RO> RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=<segredo RO>
   export RCLONE_CONFIG_S3_TYPE=s3 RCLONE_CONFIG_S3_PROVIDER=AWS RCLONE_CONFIG_S3_ENV_AUTH=true RCLONE_CONFIG_S3_REGION=us-east-1
   B=tower-media-<conta-aws>-us-east-1
   rclone copy r2:open-university-media s3:$B --checksum --metadata --s3-no-check-bucket \
     --transfers 32 --checkers 64 --log-level INFO --log-file copia-media.log
   ```
   - Usa `copy` e não `sync`: nada é apagado no S3.
   - `--metadata` leva o `Content-Type` e o `Cache-Control` de cada objeto.
   - **Verificação:**
     - `rclone size r2:open-university-media --json` e `rclone size s3:$B --json` dão o mesmo `count` e o mesmo `bytes`. A referência é 31.026 objetos e 3,388 GB em 17/11, mais o que o site subiu desde então;
     - `rclone check r2:open-university-media s3:$B --one-way --download` termina com 0 diferenças, porque compara os bytes, já que o ETag de um objeto multipart não é MD5;
     - `aws s3api head-object --bucket $B --key <uma chave>` mostra o `Cache-Control` do R2.

     A Torre registra os números no diário (`scripts/plan note`).
3. **(c) O certificado (Torre).**
   - Pede o certificado:
     ```sh
     aws acm request-certificate --region us-east-1 --domain-name media.openuniversity.si --validation-method DNS
     ```
   - Lê o registro com `aws acm describe-certificate --region us-east-1 --certificate-arn <arn> --query 'Certificate.DomainValidationOptions[0].ResourceRecord'`.
   - Cria esse CNAME de validação na zona da Cloudflare, sem proxy, porque o DNS só sai no passo 3. Ele vai junto para o Route 53, para as renovações.
   - Espera o `ISSUED` e entrega o ARN.
4. **(d) A PR do certificado.** Preenche `infra/aws/parameters.json` → `media.CertificateArn`. O `Alias` (`media.openuniversity.si`) já está lá e o `Cdn` está `on`. O deploy acrescenta o alias à distribuição com SNI e TLS 1.2. O host ainda aponta para o R2, então nada muda para o site.
5. **(e) A troca.**
   - **Uma PR leva o cliente do site ao S3:** `apps/web/src/media/server/r2.ts` passa a usar o endpoint do S3 em `us-east-1`, com a função do Lambda `open-university-web` (com `s3:GetObject`/`PutObject` no bucket) no lugar das chaves R2. A `MEDIA_PUBLIC_HOST` (`apps/web/src/media/domain/types.ts`) continua `media.openuniversity.si`, porque o host não muda, só o destino dele.
   - **Antes da troca,** a Torre roda o `rclone copy` de novo, para trazer o que o site subiu.
   - **Depois, a Torre:**
     - aponta o CNAME `media` para o `DistributionDomain`, **sem proxy**;
     - desliga o acesso público `r2.dev`;
     - revoga a chave R2 de escrita.

     O R2 fica só para leitura, como segunda cópia, e a volta é o CNAME antigo.
6. **(f) O fim do R2 (Torre).** Depois de 30 dias sem leitura no R2 (as métricas de GetObject/HeadObject do bucket a zero), apaga `open-university-media`, `the-tower-fidelity` (já refeito na AWS, ver acima) e `the-tower-media`, e revoga a chave R2 de leitura. Então segue o passo 3 (DNS).
