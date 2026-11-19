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
5. **(e) A troca.** A PR do cliente já está no `main`: com `MEDIA_STORE=s3`, `apps/web/src/media/server/r2.ts` fala com o S3 em `us-east-1` (URL virtual-hosted `https://<bucket>.s3.us-east-1.amazonaws.com/<chave>`, assinatura SigV4 do serviço `s3`), com as credenciais da própria função do Lambda (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`), nunca uma chave longa. Sem a variável, o site segue no R2 byte a byte. A `MEDIA_PUBLIC_HOST` continua `media.openuniversity.si`, porque o host não muda, só o destino dele. O ambiente do Lambda `open-university-web` **não está neste repositório**: ele vive na configuração da função e no segredo `open-university/web-env` (Q-11, passo 4, em `docs/process/host-swap-queue.md`), e só a Torre o muda. A troca, em ordem:
   1. **A permissão da função (Torre).** O nome da função de execução sai de `aws lambda get-function-configuration --function-name open-university-web --query Role --output text` (o último segmento do ARN). A política em linha, só neste bucket (o `CopyObject` precisa de `s3:GetObject` na origem e `s3:PutObject` no destino, ambos aqui; o `s3:ListBucket` faz o `HEAD` de uma chave ausente responder 404 e não 403; o bucket é SSE-S3, então não há KMS):
      ```json
      {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Sid": "MediaObjects",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
            "Resource": "arn:aws:s3:::tower-media-994763873392-us-east-1/*"
          },
          {
            "Sid": "MediaBucketList",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::tower-media-994763873392-us-east-1"
          }
        ]
      }
      ```
      ```sh
      aws iam put-role-policy --role-name <função do Lambda> --policy-name tower-media-s3 --policy-document file://media-s3.json
      ```
      A política do bucket (`60-media.json`) só nega o acesso sem TLS e só abre leitura à distribuição; não bloqueia a função da mesma conta.
   2. **O ambiente (Torre).** Acrescenta `MEDIA_STORE=s3` e `MEDIA_S3_BUCKET=tower-media-994763873392-us-east-1` ao segredo `open-university/web-env` e ao ambiente da função, sem tirar nada (o `update-function-configuration` troca o mapa inteiro, então o comando junta; nada é impresso):
      ```sh
      ENV=$(aws lambda get-function-configuration --function-name open-university-web --query Environment.Variables --output json \
        | jq -c '{Variables: (. + {MEDIA_STORE: "s3", MEDIA_S3_BUCKET: "tower-media-994763873392-us-east-1"})}')
      aws lambda update-function-configuration --function-name open-university-web --environment "$ENV" --query LastUpdateStatus --output text
      unset ENV
      aws lambda wait function-updated --function-name open-university-web
      ```
      O `AWS_REGION` o Lambda já põe. A imagem em produção ainda não lê `MEDIA_STORE`, então este passo sozinho não muda nada.
   3. **O build do site (Torre).** `aws codebuild start-build --project-name open-university-web --environment-variables-override name=SRC_SHA,value=<sha do main com esta PR>,type=PLAINTEXT`, depois `update-function-code` com `lambda-<sha7>` e a espera de `function-updated`, como nos passos 5 e 6 da Q-11. A partir daqui o site lê e escreve no S3. Prova: nos logs da função, nenhum `Storage HEAD returned HTTP 403`; um upload do admin cria a chave no bucket (`aws s3api head-object --bucket tower-media-994763873392-us-east-1 --key m/<sha>.<ext>`). Entre este passo e o 5, um upload novo vai só para o S3 e o host público ainda lê o R2: a Torre faz os passos 4 e 5 logo em seguida (ou sem uploads do admin nesse intervalo).
   4. **A cópia final R2 → S3 (Torre).** Com as variáveis `RCLONE_CONFIG_*` do passo (b), a mesma cópia leva o que o site subiu desde 18/11 18:04Z. É `copy` (nada se apaga no S3) e `--immutable` (nenhuma chave já no S3 é reescrita, o que inclui as que o site gravou depois do passo 3); `--max-age` só encurta a listagem:
      ```sh
      rclone copy r2:open-university-media s3:$B --checksum --metadata --immutable --s3-no-check-bucket \
        --max-age 2026-11-18T18:04:00Z --transfers 32 --checkers 64 --log-level INFO --log-file copia-delta.log
      rclone size r2:open-university-media --json; rclone size s3:$B --json
      rclone check r2:open-university-media s3:$B --one-way --download
      ```
      Prova: o `count` do S3 é o do R2 mais os uploads feitos depois do passo 3 (nunca menos), e o `check --one-way` termina com 0 diferenças. A Torre registra os números no diário (`scripts/plan note`).
   5. **O DNS de `media` (Torre).** Na Cloudflare, o registro `media` vira um CNAME **só DNS (proxy desligado)** para o `DistributionDomain` da stack `tower-app-media` (o `xxxx.cloudfront.net`). No Route 53, a stack `70-dns.json` já tem os aliases A/AAAA `media` para a distribuição (`RecordMediaA`, `RecordMediaAaaa`), que valem quando a zona for para lá (passo 3 do DNS). Prova: `curl -sI https://media.openuniversity.si/<chave de uma capa>` responde 200 com `x-cache` e `via` do CloudFront. Depois, desliga o acesso público `r2.dev`.
   6. **O R2 fica só para leitura (Torre).** Acompanha as leituras do bucket `open-university-media` (as métricas de GetObject/HeadObject do R2 no painel da Cloudflare) até zerarem; então revoga a chave R2 de **escrita**. O R2 fica como segunda cópia por 30 dias sem leitura e então sai no passo (f).

   **A volta:** tirar `MEDIA_STORE` do ambiente da função (o mesmo comando do passo 2, com `del(.MEDIA_STORE, .MEDIA_S3_BUCKET)`) põe o site de novo no R2, e o CNAME antigo devolve o host público. Os uploads feitos no S3 durante a troca não estão no R2: a volta copia esses de S3 para R2 com o mesmo `rclone copy` no sentido inverso.
6. **(f) O fim do R2 (Torre).** Depois de 30 dias sem leitura no R2 (as métricas de GetObject/HeadObject do bucket a zero), apaga `open-university-media`, `the-tower-fidelity` (já refeito na AWS, ver acima) e `the-tower-media`, e revoga a chave R2 de leitura. Então segue o passo 3 (DNS).

## Passo 3: execução
**O que esta PR traz.** O passo 3 fica a uma PR de distância, a que traz a exportação:
- **`scripts/dns-zone`** (`scripts/lib/dns_zone.py`), offline, sem rede:
  - `build <arquivo-bind>` lê a exportação BIND da Cloudflare (`$ORIGIN`, `$TTL`, comentários, TXT com várias strings, MX, SRV, CAA, CNAME, A/AAAA, NS e SOA) e escreve a lista de registros `infra/aws/dns/openuniversity.si.json` e a stack `infra/aws/stacks/70-dns.json`, gerada dela;
  - `compare <arquivo-bind>` confere a exportação contra a lista versionada: todo registro, com os mesmos valores e o mesmo TTL. Sai com 1 numa diferença;
  - `dig-plan --ns <os 4 NS> --site <SiteDistribution>` gera um `dig` por registro, com a resposta esperada;
  - `template --check` prova que a stack é a da lista (o teste `test_dns_zone.py` também).
- **Os registros com proxy são recusados.** A exportação traz o IP anycast da Cloudflare (ou, num CNAME com proxy, o alvo que ela fronteia), nunca a origem. Esses registros vão para `needs_target`, e o alvo real entra em `infra/aws/dns/openuniversity.si.targets.json`. As faixas da Cloudflare ficam em `infra/aws/dns/cloudflare-ips.json`, com a fonte (`cloudflare.com/ips-v4` e `ips-v6`). **Elas precisam ser atualizadas antes do `build`**, porque foram escritas de memória, sem busca.
- **O NS e o SOA do apex são descartados**, porque o Route 53 cria os dele. O TTL automático da Cloudflare (1 na exportação) vira 300 s.
- **O apex.** Um CNAME no apex (a Cloudflare o achata) para `*.cloudfront.net` vira alias A e AAAA para o parâmetro `SiteDistribution`, com a zona do CloudFront `Z2FDTNDATAQYW2`. O `www` continua CNAME. Enquanto o parâmetro está vazio, o apex não tem registro.
- **Um alvo pode ser uma exportação do CloudFormation.** Em `openuniversity.si.targets.json`, o alvo `{"alias_import": "<nome da exportação>"}` vira alias A e AAAA cujo `DNSName` é o `Fn::ImportValue` dessa exportação, com a zona do CloudFront `Z2FDTNDATAQYW2`. A sessão não lê saídas de stack, então o domínio nunca é copiado à mão. O `media` usa isso: a saída `DistributionDomain` da `tower-app-media` (só com `Cdn=on`) é exportada como `tower-media-distribution-domain`, e o `media.openuniversity.si` da zona é alias A e AAAA para ela. A distribuição já tem o alias `media.openuniversity.si` com o certificado do ACM e IPv6 ligado.
  - **A ordem.** Uma importação precisa da exportação antes, então `order.json` põe `dns` depois de `media` (`"dns": ["media"]`; o `StackOrderTests` deriva a aresta das importações). O deploy implanta o `dns` sempre que implanta o `media`, e espera o `media` acabar quando as saídas dele mudaram (DEP7-CRITICAL-PATH).
  - **A trava.** Enquanto a `tower-app-dns` importa a exportação, o CloudFormation recusa mudar ou apagar a `tower-media-distribution-domain` na `tower-app-media`: `Cdn=off`, uma troca da distribuição que mude o domínio ou apagar a stack falham. A exportação fica enquanto o `dns` a importa. Para trocar, primeiro uma PR tira o alvo do `media` (ou o aponta para outra coisa) e o deploy atualiza o `dns`; só depois a exportação muda.
- **A stack `tower-app-dns`** (depois de `media` em `order.json`):
  - com `Zone=off` (o `parameters.json` de hoje), só um `WaitConditionHandle`, que não cobra nada. A fronteira `tower-boundary` só permite o Route 53 depois que a Torre reaplica o `tower-bootstrap` com a declaração `TheSiteZoneOnRoute53`;
  - com `Zone=on` e a lista vazia, só a zona, retida (`Retain`), com os quatro NS na saída `NameServers`;
  - com a lista, um `AWS::Route53::RecordSet` por nome e tipo, com o TXT entre aspas e partido em strings de 255.
- **O custo:** US$ 0,50 por mês pela zona, mais US$ 0,40 por milhão de consultas (as consultas de alias ao CloudFront são grátis). O volume de consultas não é medido, então o teto é 10 milhões por mês: no máximo US$ 4,50 por mês, contra o limite de US$ 150 (o teste `DnsStackTests` confere).

**O que acontece depois, e quem faz:**
1. **(a) A fronteira (Torre).** Reaplica o `tower-bootstrap` com este `bootstrap.json`, com `UsePreviousValue` nos parâmetros. Uma reaplicação só serve ao MEDIA-S3 e a esta. O hash está em `test_infra_aws.py`. Feito isso (18/11), a PR do passo 3 (d) põe `dns.Zone=on` junto com a lista completa, e o deploy cria a zona já com todos os registros (nunca vazia, nunca antes de a lista estar certa).
2. **(b) Os NS (Torre).** Lê a saída `NameServers` da stack `tower-app-dns` e entrega os quatro NS.
3. **(c) A exportação (Torre).** Entrega a exportação BIND da zona `openuniversity.si` (Cloudflare, DNS, Records, Export) e as duas listas atuais de `cloudflare.com/ips-v4` e `ips-v6`. Diz também:
   - o alvo real de cada registro com proxy (o `media` vai para o `DistributionDomain` da stack `tower-app-media`, sem proxy, pela exportação `tower-media-distribution-domain` com `alias_import`);
   - se o DNSSEC está ligado (`dig DS openuniversity.si +short` não vazio).
4. **(d) A PR do passo 3 (sessão).**
   - atualiza `cloudflare-ips.json`;
   - roda `scripts/dns-zone build <exportação>`;
   - põe os alvos reais em `openuniversity.si.targets.json`;
   - põe `dns.SiteDistribution` no `parameters.json` (o `build` diz o valor) e `dns.Zone=on`;
   - roda `scripts/dns-zone compare <exportação>` até sair com 0.

   O deploy do merge cria os registros. Nada muda para o site, porque o registrador ainda aponta para a Cloudflare.
5. **(e) A conferência ao vivo (Torre).** Roda `scripts/dns-zone dig-plan --ns <os 4 NS> --site <SiteDistribution>` e cada `dig` que ele lista, contra o NS do Route 53. Cada resposta tem de ser a esperada. Uma diferença volta para (d), e a troca não acontece.
6. **(f) O DNSSEC, se estiver ligado (Torre).** Apaga o DS no registrador e espera o TTL do DS passar antes da troca. Se não fizer isso, os resolvedores que validam DNSSEC deixam o domínio sem resposta.
7. **(g) A troca dos NS (Torre),** só depois de (e) e de (f). No painel da OpusDNS/Hostinger, os NS de `openuniversity.si` passam a ser os quatro do Route 53. A volta é pôr de novo os dois NS da Cloudflare, e a zona dela fica intacta até o passo 4.
8. **(h) A espera do TTL.** Espera pelo menos o maior TTL entre o NS da zona-pai (`dig NS openuniversity.si @<um NS do .si>`, em geral 86.400 s) e os registros da lista. Na prática são 48 horas. Depois disso, `dig NS openuniversity.si @1.1.1.1` e `@8.8.8.8` têm de dar só o Route 53, e o site, o e-mail e as mídias têm de responder.
9. **(i) O passo 4 (Torre).** Revoga os tokens da API da Cloudflare e as chaves R2 que restarem. Depois apaga a zona `openuniversity.si` na Cloudflare, já com a troca propagada.

## Bloqueios achados na resposta da Torre (18/11)
A Torre exportou a zona e conferiu o DNSSEC (desligado, sem DS). A exportação mostra duas coisas que o runbook não cobria. As duas bloqueiam a troca de NS do passo 3 e o apagamento da zona do passo 4, mas não bloqueiam o resto.

1. **O e-mail de `openuniversity.si` passa pelo Cloudflare Email Routing.**
   - Os registros são os MX `route1/2/3.mx.cloudflare.net`, o DKIM `cf2024-1._domainkey` e o SPF `include:_spf.mx.cloudflare.net`.
   - O roteamento só funciona com a zona ativa na Cloudflare. Copiar esses registros para o Route 53 mantém os nomes, mas a troca de NS desativa a zona lá e, com ela, o roteamento. Apagar a zona no passo 4 também o desliga.
   - **Antes da troca de NS, o e-mail precisa de um substituto.** O caminho que fica na AWS é o recebimento do SES (MX `inbound-smtp.us-east-1.amazonaws.com`), uma regra que encaminha para o destino de hoje e o DKIM e o SPF do SES. Ele está pronto, desligado: ver [E-mail: o substituto na AWS](#e-mail-o-substituto-na-aws).
   - Isso é infraestrutura nova, que entra pelas stacks. O destino atual de cada endereço é configuração da conta Cloudflare, que só a Torre lê, e o encaminhamento envolve o e-mail de pessoas. Por isso a Torre informa os endereços e os destinos e o dono confirma o substituto antes do corte.
2. **As outras zonas da conta, `thetower.si`, `atorre.digital` e `theopenuniversity.si`, dependem do proxy e de Page Rules da Cloudflare.**
   - Cada uma faz um redirecionamento 301 para `openuniversity.si`.
   - A `thetower.si` também tem e-mail pelo ImprovMX e uma verificação do Google.
   - Sair da Cloudflare de vez exige levar esses redirecionamentos para a AWS (por exemplo, uma distribuição CloudFront com uma função de redirecionamento, ou um bucket S3 de redirect) e as zonas para o Route 53.
   - A D-323 só nomeia `openuniversity.si`. As outras três são passos novos, e o passo 4 (revogar credenciais) espera por elas.

**O que já segue sem esperar esses bloqueios:**
- a zona `openuniversity.si` no Route 53, com todos os registros, incluindo os três CNAME de validação do ACM. Ela não atende ninguém antes da troca de NS. A PR do passo 3 (d) liga `dns.Zone=on` com `dns.SiteDistribution` e a lista completa: o deploy cria a zona já com todos os registros (os MX, o DKIM e o SPF do Email Routing como exportados, até o substituto do e-mail), e a saída `NameServers` é o que a Torre lê em (b).
- a distribuição de mídia com o alias, que fica sem tráfego até o CNAME de `media` apontar para ela.
- a troca do cliente do site para o S3.

**Nota sobre a chave R2 só de leitura (`R2_ACCESS_KEY_ID_RO`):** ela recebe 403 no `ListObjectsV2` do `open-university-media`. A Torre copiou pela API da Cloudflare e pelo host público. O cliente do site deixa o R2 no corte, então esse acesso some com ele.

## E-mail: o substituto na AWS
**O que já está no repositório, desligado.** A stack `tower-app-mail` (`infra/aws/stacks/65-mail.json`) substitui o Cloudflare Email Routing pelo recebimento do SES. Com `mail.Mail=off` (o `parameters.json` de hoje), ela é só um `WaitConditionHandle`: o merge não muda nada e não cobra nada.
- **Com `Mail=on`**, a stack cria:
  - a identidade de domínio do SES para `openuniversity.si` (parâmetro `Domain`), com Easy DKIM de 2048 bits. Os três tokens saem como exportações `tower-mail-dkim-name-<n>` e `tower-mail-dkim-value-<n>`;
  - um bucket S3 privado (acesso público bloqueado, dono imposto, SSE-S3, só TLS), retido. O SES grava ali cada mensagem bruta em `inbox/<id da mensagem>`, e só as regras do conjunto `tower-mail` desta conta podem gravar. O ciclo de vida apaga cada mensagem em **30 dias**. O bucket é a rede de segurança: guarda o que chegou enquanto o mapa está vazio, quando o encaminhamento falha ou quando o spam é barrado. Trinta dias cobrem uma falha notada na revisão semanal, as 72 horas que o SES leva para achar o DKIM e a janela do corte. Mais que isso seria guardar e-mail de pessoas sem uso, e a cópia que fica é a do destino;
  - o conjunto de regras `tower-mail`, com uma regra para todo destinatário do domínio, com TLS opcional e verificação de spam e vírus ligada. **O CloudFormation não consegue tornar um conjunto de regras ativo** (o `AWS::SES::ReceiptRuleSet` só tem o nome), então ativar o conjunto é passo da Torre.
- **Sem mapa** (`MapParameter` vazio, o padrão), a regra é `tower-mail-store`: ela só grava no bucket e nada é enviado. Não existe Lambda, papel nem permissão de envio.
- **Com mapa** (`MapParameter` é o nome de um parâmetro SSM, por exemplo `/tower/mail/forward-map`), a regra vira `tower-mail-forward`: ela grava primeiro e depois chama a Lambda `tower-mail-forwarder`, de forma assíncrona. A Lambda:
  - lê o mapa no SSM a cada mensagem. O mapa é um JSON `{"<endereço ou parte local>": "<destino>" | ["<destino 1>", "<destino 2>"]}`;
  - descarta a mensagem que o SES marcou como spam ou vírus (ela fica no bucket);
  - troca o `From` por `"<nome> via openuniversity.si" <forward@…>` (parâmetro `SenderLocalPart`, no domínio verificado) e põe o `From` original no `Reply-To`, a não ser que já exista um. Também tira `Return-Path`, `Sender`, `Message-ID` e `DKIM-Signature`, como no encaminhador padrão do SES;
  - envia pelo SES v2 só com esse remetente, porque o papel `tower-app-mail-forwarder` só pode enviar com `ses:FromAddress` igual a ele. Um destinatário fora do mapa não recebe nada. O log registra o id da mensagem e quantos destinos teve, nunca um endereço.
- **Os endereços nunca entram no repositório.** O mapa é configuração do dono. A Torre o grava no SSM, e o repositório só tem o nome do parâmetro. O teste `test_no_address_of_anyone_is_in_the_tree` confere `infra/aws`, `scripts/lib/dns_zone.py` e este documento.
- **Por que `65` e não `80`.** No corte, a stack `dns` importa os tokens de DKIM da `mail`. O `order.json` exige que uma stack venha antes da que a importa, também pela numeração dos arquivos. Por isso a `mail` vem antes da `dns` (`"mail": []`).
- **O DKIM.** Os tokens do Easy DKIM só existem depois que a identidade é criada, então não dá para escrevê-los na lista. Eles também não são copiados à mão: no corte, a stack `dns` ganha três CNAME cujo nome e valor são o `Fn::ImportValue` das exportações da `mail`. Só a `dns` escreve na zona, como antes. Enquanto a Cloudflare ainda for a autoritativa, a Torre copia esses três CNAME para lá (passo 4 abaixo). Assim o domínio é verificado antes do corte.
- **A fronteira.** O `tower-bootstrap` ganhou `ses:*` na declaração por região (`WorkloadServicesInTheStackRegion`). Para caber, duas negações viraram padrões que negam o mesmo ou mais: `iam:CreatePolicy*` e `iam:*LoginProfile`. O arquivo tem 51.104 bytes, 96 abaixo do limite de 51.200.
- **O custo.** Com Mail off, zero. Com Mail on, o teto declarado é de **US$ 3,20 por mês** para 10.000 mensagens de até 256 KB. São US$ 1,00 do recebimento (US$ 0,10 por mil), US$ 0,90 dos blocos de 256 KB (US$ 0,09 por mil), US$ 1,00 do envio (US$ 0,10 por mil), mais US$ 0,12 por GB, menos de US$ 0,10 de S3, e a Lambda fica no nível gratuito. Isso é cerca de 2% do orçamento de US$ 150 (o teste `MailStackTests` confere).

**O corte em uma PR.** O `scripts/dns-zone build infra/aws/dns/openuniversity.si.zone --mail ses` reescreve a lista e a stack `70-dns.json` com:
- o MX do apex `10 inbound-smtp.us-east-1.amazonaws.com`, escrito como `Fn::Sub` de `${AWS::Region}` (o recebimento do SES existe em `us-east-1`, a região das stacks);
- o SPF `v=spf1 include:amazonses.com ~all`. Só o `include` da Cloudflare é trocado; outros mecanismos ficam;
- sem o DKIM `cf2024-1._domainkey` da Cloudflare;
- o DMARC `_dmarc` `v=DMARC1; p=none`, só se não houver um. O `p=none` só observa, e o DKIM do SES alinha o `From` reescrito;
- os três CNAME do DKIM, importados.

A mesma PR passa o `order.json` para `"dns": ["media", "mail"]`, e o `build` avisa disso. O `compare` continua valendo, porque aplica a mesma troca à exportação. Para reverter, a PR roda o mesmo `build` sem `--mail` (o padrão é `cloudflare`).

**O que o dono decide.**
- Os endereços de `openuniversity.si` e o destino de cada um. Hoje eles estão no Cloudflare Email Routing, que só a Torre lê. A Torre os informa e o dono confirma.
- O remetente do encaminhamento (a parte local `forward` no domínio é o padrão de `SenderLocalPart`) e os 30 dias de guarda.

**Os passos da Torre**, nesta ordem:
1. **Reaplicar o `tower-bootstrap`** com o modelo do `main` (change set, `UsePreviousValue` nos parâmetros) e informar o hash canônico. O `APPLIED` do `test_infra_aws.py` já tem o desta PR: `f3b82e30…e5d5`.
2. **Pedir o acesso de produção do SES** em `us-east-1` (console ou `aws sesv2 put-account-details`). No sandbox, o SES só envia para endereços verificados, até 200 por dia, então o encaminhamento para destinos de pessoas não funciona. Só a Torre faz esse pedido.
3. Depois da PR que liga `mail.Mail=on`, **ler as saídas** da `tower-app-mail` (`InboxBucket`, `RuleSetName`, `DkimName1..3` e `DkimValue1..3`).
4. **Verificar o domínio.** Pôr os três CNAME do DKIM na zona da Cloudflare, sem proxy, e esperar a identidade ficar `SUCCESS` (`aws sesv2 get-email-identity --email-identity openuniversity.si`).
5. **Ativar o conjunto de regras.** Primeiro `aws ses describe-active-receipt-rule-set`: se houver outro ativo, parar e informar. Depois `aws ses set-active-receipt-rule-set --rule-set-name tower-mail`. Sem o MX, nada chega por ele.
6. **Gravar o mapa** com os endereços e destinos que o dono confirmou: `aws ssm put-parameter --name /tower/mail/forward-map --type SecureString --value '<o JSON>'`. Depois, uma PR põe `mail.MapParameter` com esse nome.
7. **Testar de ponta a ponta antes do MX.** Enviar uma mensagem para um endereço do mapa direto ao `inbound-smtp.us-east-1.amazonaws.com` (por exemplo, `swaks --server`). Conferir quatro coisas: o objeto em `inbox/` no bucket, a linha `"forwarded": 1` no log `/aws/lambda/tower-mail-forwarder`, a chegada ao destino com `From` "… via openuniversity.si" e o `Reply-To` do remetente, e o DKIM `pass` com `d=openuniversity.si`.
8. **O corte do MX com a troca de NS.** A PR do corte (`--mail ses` e o `order.json`) entra logo antes da troca de NS do passo 3 (b). Durante a propagação, o MX da Cloudflare e o do SES entregam nos mesmos destinos.

**Para reverter.**
- **Só o encaminhamento:** a Torre grava `{}` no mapa, o que vale na hora e sem deploy. Ou uma PR esvazia `MapParameter`, e a regra volta a só gravar.
- **Antes do corte:** a Torre desativa o conjunto (`aws ses set-active-receipt-rule-set`, sem nome), porque o CloudFormation não apaga um conjunto ativo. Depois, uma PR põe `Mail=off`. A identidade sai com ela, e o bucket fica retido e se esvazia em 30 dias.
- **Depois do corte:** primeiro a PR de reversão do corte (`build` sem `--mail` e `"dns": ["media"]`), porque a `mail` não pode tirar as exportações enquanto a `dns` as importa. Com o NS já no Route 53, o Email Routing da Cloudflare não volta sozinho. Voltar o e-mail para a Cloudflare é voltar o NS (a reversão do passo 3).

## O corte da mídia, feito (18/11)
A Torre fez os passos 1 a 5 do corte entre 20:43 e 20:49Z, e a sessão conferiu o resultado de fora.
- **Os passos:**
  1. A política `tower-media-s3` foi posta no papel do Lambda.
  2. `MEDIA_STORE=s3` e `MEDIA_S3_BUCKET` entraram no Lambda e no segredo `open-university/web-env`.
  3. O build `lambda-19f92d4` está no ar.
  4. A cópia final teve delta zero: nenhum objeto entrou depois de 18:04Z, e o S3 continua idêntico.
  5. O `media` agora é um CNAME só de DNS para a distribuição de mídia.
     - Antes, o registro era gerado pelo domínio personalizado do R2, e por isso a Torre tirou esse domínio do bucket.
     - O `r2.dev` já estava desligado, então o R2 ficou sem acesso público.
- **A conferência:** a home responde 200. Uma mídia da home responde `server: AmazonS3` e `via: CloudFront`, e os logs do Lambda não mostram erro de armazenamento.
- **Ainda falta provar:** que um upload feito pelo site cai no S3. Basta o primeiro upload de admin.
- **O caminho de volta:** apagar o CNAME e recriar o domínio personalizado do R2 no bucket.

**O que fica com o dono:**
- **A revogação da chave de escrita do R2.** O conector da Torre não lê nem revoga tokens da Cloudflare: falta o escopo `account-api-tokens.write`. A revogação é no painel, em R2 → Manage API tokens. O Lambda antigo só tinha a chave de leitura.
- **Os endereços e destinos do e-mail.** O conector também não lê o Email Routing: faltam `zone-settings.read`, `email-routing-rule.read` e `email-routing-address.read`. Eles vêm do painel, em Email → Routing.

**Decisões de 18/11:**
- **O dono (Daniel, 17:42 BRT), sobre as outras zonas:**
  - só `theopenuniversity.si` continua redirecionando para `openuniversity.si`, agora na AWS, com o desenho feito pela sessão;
  - `thetower.si` e `atorre.digital` deixam de redirecionar, sem substituto.
- **A Torre:** a guarda de 30 dias das mensagens fica, e o remetente do encaminhamento se chama "Open University".

## Respostas da Torre de 18/11 (~18:15 BRT)
- **O token de escrita do R2 foi revogado.** O `R2 Account Token` foi apagado às 21:10Z.
  - Ficam quatro tokens: `open-university-ci-ro` (só leitura, `open-university-media`), `tower-ro` (só leitura, `the-tower-*`), `tower-rw` (`the-tower-fidelity` e `the-tower-media`) e o token de usuário `Editar Cloudflare Workers`, que é admin.
  - Eles saem na revogação final, depois da troca de NS.
- **O upload pelo caminho real do site está provado.**
  - Às 21:13:24Z, um `POST /api/admin/media/objects` com uma WebP de 324 bytes respondeu 200, com `m/f3deca3f…a2f7.webp`.
  - O `head-object` no S3 traz o `VersionId`, `AES256` e `public, max-age=31536000, immutable`.
  - A URL pública responde 200, com `server: AmazonS3` via CloudFront e o mesmo sha256 do arquivo enviado.
- **O bootstrap foi reaplicado com `ses:*`** pelo change set `req-d323-ses`, às 21:11:50Z. O sha256 canônico é `f3b82e30…e5d5`.
- **O acesso de produção do SES foi pedido** em us-east-1 e está `PENDING` na revisão da AWS. Enquanto isso vale a cota do sandbox: 200 por dia e 1 por segundo.
- **`theopenuniversity.si` não estava na Cloudflare.**
  - Os NS são `atlas/hyperion.dns-parking.com`, o estacionamento do registrador (Hostinger), e não há DS.
  - O apex e o www apontam para sobras do host antigo, e `http://theopenuniversity.si/` responde 500.
  - O redirecionamento não funciona hoje, então trocar os NS para a zona do Route 53 não perde nada.
  - **Ordem:**
    1. Trocar os NS no registrador para os quatro da saída `NameServers` de `tower-app-redirect`.
    2. Pedir o certificado ACM para o apex e o www, e validar pelo botão "Create records in Route 53". Esses dois CNAME de validação ficam fora da stack, o que é aceitável: o CloudFormation não apaga registros que não criou.
    3. Um PR põe o `CertificateArn`.
    4. Conferir com `curl -sI https://www.theopenuniversity.si/x?y=1`.

## E-mail e theopenuniversity.si (18/11 ~18:47 BRT)
**E-mail:**
- **O DKIM foi verificado.** Os três CNAME estão na zona da Cloudflare, e a identidade SES de `openuniversity.si` dá `DkimAttributes.Status = SUCCESS` e `VerifiedForSendingStatus = true` desde 21:46Z.
  - Na zona do Route 53, esses três CNAME chegam com o PR do corte (`scripts/dns-zone build ... --mail ses`), que os importa da stack de e-mail. Ninguém os escreve à mão, porque um registro manual faria o CREATE do CloudFormation falhar.
- **O rule set `tower-mail` está ativo**, com a regra `tower-mail-store`. O MX continua na Cloudflare, então nada chega a ele ainda.
- **O mapa está em `/tower/mail/forward-map`:** SecureString, versão 1, com duas entradas. Nenhum endereço está no repositório.
- **O acesso de produção do SES foi NEGADO** (caso 179503637000266), porque ainda não havia identidade verificada. A Torre responde o caso agora que o domínio está verificado.
- **Caminho enquanto o sandbox durar, aceito pelo desenho:**
  - Os dois endereços encaminham para a caixa do próprio dono. Em sandbox, o SES envia para identidades verificadas, então verificar esse destino como identidade de e-mail faz o encaminhamento funcionar antes da aprovação.
  - O dono clica no link que o SES manda.
  - A cota do sandbox, de 200 por dia, cobre o volume de cerca de 48 por dia.
  - O pedido de produção continua, para tirar a dependência dessa verificação.

**theopenuniversity.si:**
- **A zona é `Z03672211K9Z57D4JOTHY`.** Os NS estão sendo trocados no registrador para `ns-630.awsdns-14.net`, `ns-1578.awsdns-05.co.uk`, `ns-84.awsdns-10.com` e `ns-1419.awsdns-49.org`.
- **O certificado** é `arn:aws:acm:us-east-1:994763873392:certificate/302c7003-…`, para o apex e o www, e está `PENDING_VALIDATION` até a troca propagar.
  - Os dois CNAME de validação estão na zona e ficam fora do template. O CloudFormation não apaga um registro que não criou, e o ACM renova pelo mesmo CNAME.
  - O PR do `CertificateArn` só entra depois de o certificado estar `ISSUED`, porque um certificado ainda não emitido faria o update da distribuição falhar.

## Revogação e o R2 apagado (18/11 ~20:42 e 20:58 BRT)
Daniel mandou não esperar as 48 h nem os 30 dias. Pela Torre:
- **Chaves R2 fora das cópias:** saíram `R2_ACCESS_KEY_ID_RO`, `R2_SECRET_ACCESS_KEY_RO` e `R2_ACCOUNT_ID` do segredo
  `open-university/web-env` e do ambiente da Lambda `open-university-web`; os arquivos de R2 da caixa foram apagados.
- **R2 apagado:** `open-university-media` (31.026 objetos) e `the-tower-media` (1.329) foram esvaziados e apagados às
  20:57 BRT, depois que a listagem do S3 bateu (SHA-256 `f9eaf5c8…e581f`) e a única chave que faltava foi copiada.
  Às 21:01 BRT, com o ok de Daniel, `the-tower-fidelity` (1.178 objetos, máscaras da era Origin) foi apagado sem cópia
  (job `8f37a878-593c-470b-9219-d3ca012ea9f8`). O R2 está vazio (GET /r2/buckets: lista vazia).
- **Não revogados:** os tokens `open-university-ci-ro`, `tower-ro`, `tower-rw` e `Editar Cloudflare Workers`. O conector
  da Torre não tem permissão de API Tokens (403), então isso pede o login de Daniel no painel. As zonas ficam até o fim da
  propagação dos NS.
- **O risco que nasce:** sem o R2, a mídia tem uma cópia só, numa conta e numa região. O versionamento cobre apagar ou
  sobrescrever, mas não uma conta comprometida. `RISK-media-single-account` registra isso. O tratamento é replicar para
  outra região (menos de um dólar por mês) e espera o ok de Daniel, porque é gasto.

## A cópia da mídia em outra região (19/11, RISK-media-single-account)
Daniel aprovou em 18/11 às 21:29 BRT uma cópia do bucket de mídia numa segunda região da AWS, abaixo de US$ 1 por mês.
**O caminho mais barato:** S3 Cross-Region Replication (CRR) para um bucket em `us-west-2`, gravado direto como Glacier
Instant Retrieval. Uma cópia feita à mão pela Torre, sem stack, custaria menos código, mas deixaria um bucket e um papel fora
do IaC e da fronteira; outra conta com Object Lock cobriria também uma conta comprometida, mas pede uma conta nova (do
dono) e fica para depois.

**O que esta PR traz.**
- **`infra/aws/stacks/58-media-replica.json`** (`tower-app-media-replica`): o bucket `tower-media-replica-<conta>-us-west-2`,
  versionado, SSE-S3, privado, dono imposto, retido, só por TLS, versões antigas apagadas em 90 dias. Vem antes de `60-media`
  porque o `media` precisa dele (`order.json`: `"media": ["media-replica"]`; nenhum `ImportValue` cruza regiões, então o
  `StackOrderTests` deriva a aresta do nome `tower-media-replica-` no modelo do `media`).
- **`infra/aws/regions.json`** (`{"media-replica": "us-west-2"}`): o `deploy.sh` passa `--region` a toda chamada do
  CloudFormation dessa stack (deploy, execute-change-set, describe-stacks, eventos, rollback) e a região entra no hash dela.
  As outras stacks ficam na região do build, como antes.
- **`60-media.json`**: o parâmetro `ReplicaRegion` (vazio: nada muda) cria o papel `tower-app-media-replication` (com a
  fronteira) e a regra de replicação do bucket inteiro: toda versão nova vai para a réplica como `GLACIER_IR`, e um
  delete marker **não** é replicado, então apagar no `us-east-1` não apaga a cópia. O papel lê só o bucket de mídia e só
  escreve `ReplicateObject`/`ReplicateTags` na réplica; o mesmo papel serve ao job de Batch Replication
  (`s3:InitiateReplication`, `s3:PutInventoryConfiguration`). O `parameters.json` liga com `ReplicaRegion=us-west-2`.
- **`bootstrap.json`**: o novo parâmetro `ReplicaRegion` (padrão vazio) e a condição de região da declaração
  `WorkloadServicesInTheStackRegion` vira `[região da stack, ReplicaRegion]`; as ARNs de stack do deployer dizem
  `cloudformation:*` na região (a fronteira as segura nas duas). Para caber (sobravam 96 bytes), quatro negações viraram
  padrões que negam o mesmo ou mais: `codebuild:*Project`, `lambda:DeleteFunction*`, `lambda:*Permission`,
  `iam:*RolePermissionsBoundary`. 51.155 bytes.

**Custo.** 3,4 GB em ~32 mil objetos. Por GB-mês: Standard US$ 0,023, Standard-IA US$ 0,0125, Glacier IR US$ 0,004
(os dois últimos cobram no mínimo 128 KB por objeto). Mesmo com 128 KB a mais em cada objeto (até 7,3 GB), o Glacier IR
dá cerca de **US$ 0,03 por mês**; o Standard daria US$ 0,08. Uma vez: cerca de **US$ 1** (32 mil PUTs de replicação a
US$ 0,02 por mil, 3,4 GB entre regiões a US$ 0,02/GB, US$ 0,25 do job e US$ 1 por milhão de objetos). Restaurar tudo:
US$ 0,03/GB de leitura, cerca de US$ 0,45 com as requisições e a transferência.

**Passos da Torre, em ordem.**
1. **Antes do merge desta PR: reaplicar o `tower-bootstrap`** com este modelo, `ReplicaRegion=us-west-2` e
   `UsePreviousValue` nos outros parâmetros. Sem isso, o deploy do merge falha na `tower-app-media-replica` (a fronteira
   recusa `us-west-2`), o `media` e o `dns` não começam e o `last-sha` não anda.
   ```
   aws cloudformation create-change-set --region us-east-1 --stack-name tower-bootstrap --change-set-name req-media-replica \
     --template-body file://infra/aws/bootstrap.json --capabilities CAPABILITY_NAMED_IAM \
     --parameters ParameterKey=OriginRepoUrl,UsePreviousValue=true ParameterKey=BaseBranch,UsePreviousValue=true \
       ParameterKey=DoorbellTokenSha256,UsePreviousValue=true ParameterKey=AlertEmail,UsePreviousValue=true \
       ParameterKey=ReplicaRegion,ParameterValue=us-west-2
   aws cloudformation describe-change-set --region us-east-1 --stack-name tower-bootstrap --change-set-name req-media-replica \
     --query 'Changes[].ResourceChange.[LogicalResourceId,Action,Replacement]' --output text
   ```
   Esperado: `Boundary Modify False` e `DeployerRole Modify False`, nada mais. Então `execute-change-set` e, no fim, o
   `get-template` canônico dá o `APPLIED` de `test_infra_aws.py` (`ea269641…fcda3`).
2. **O deploy do merge** cria `tower-app-media-replica` em `us-west-2` e depois atualiza `tower-app-media` com o papel e a
   regra. Prova:
   ```
   ACCT=$(aws sts get-caller-identity --query Account --output text)
   SRC=tower-media-$ACCT-us-east-1; DST=tower-media-replica-$ACCT-us-west-2
   aws cloudformation describe-stacks --region us-west-2 --stack-name tower-app-media-replica --query 'Stacks[0].StackStatus'
   aws s3api get-bucket-replication --bucket $SRC --query 'ReplicationConfiguration.Rules[0].[Status,Destination.Bucket,Destination.StorageClass]'
   ```
3. **Os objetos de antes da regra (uma vez).** A CRR só copia o que é escrito depois dela; o resto vai por um job de S3
   Batch Replication com manifesto gerado, sem relatório (a verificação é o passo 4):
   ```
   aws s3control create-job --region us-east-1 --account-id $ACCT \
     --operation '{"S3ReplicateObject":{}}' \
     --manifest-generator '{"S3JobManifestGenerator":{"ExpectedBucketOwner":"'$ACCT'","SourceBucket":"arn:aws:s3:::'$SRC'","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true,"ObjectReplicationStatuses":["NONE","FAILED"]}}}' \
     --report '{"Enabled":false}' --priority 10 \
     --role-arn arn:aws:iam::$ACCT:role/tower-app-media-replication \
     --no-confirmation-required --client-request-token media-replica-backfill-1 \
     --description 'media: the objects older than the replication rule'
   aws s3control describe-job --region us-east-1 --account-id $ACCT --job-id <JobId> \
     --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed]'
   ```
   Esperado: `Complete`, falhas 0 (um `FAILED` volta no mesmo comando com outro `--client-request-token`).
4. **A verificação: contagem e bytes dos dois lados.**
   ```
   aws s3 ls s3://$SRC --recursive --summarize | tail -n 2
   aws s3 ls s3://$DST --recursive --summarize --region us-west-2 | tail -n 2
   aws s3api head-object --bucket $SRC --key <uma chave m/...> --query ReplicationStatus   # COMPLETED
   ```
   `Total Objects` e `Total Size` iguais (as versões atuais; um upload do site entre os dois `ls` aparece primeiro no
   primeiro, e chega à réplica em minutos). Com isso, uma PR registra a prova: `RISK-media-single-account` sai de `assessed`
   e o `DATA-r2-media` ganha a data da verificação.

**Reverter.** `ReplicaRegion` vazio no `parameters.json` tira a regra e o papel; o bucket da réplica é retido (apagar é à
mão, pela Torre). Voltar o `bootstrap.json` pede outra reaplicação.

**O que fica fora.** Uma conta comprometida ou fechada ainda leva as duas cópias (mesma conta, sem Object Lock); a regra
`tower-app-stack-state` do EventBridge só vê stacks de `us-east-1`, então os eventos da `tower-app-media-replica` não chegam
à porta (o `deploy.sh` espera a stack pelo `describe-stacks`).
