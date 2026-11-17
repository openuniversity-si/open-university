# The AWS architecture against its scope (review of 16/11/2026)

Daniel asked on 10/11 for a review of the whole AWS architecture, and the Torre ordered it on 16/11. Since 13/11, AWS keeps only two jobs:
- **the deploy:** a merge into GitHub `main` → doorbell → CodeBuild `tower-infra-deploy` (`infra/aws/deploy.sh`). A code-only merge goes live by the merge queue's pointer swap.
- **the site:** the ECS service `tower-service`, the port Lambda behind API Gateway, and the RDS database.

The Origin-era code stays dormant on purpose (D-316).

What was read: `infra/aws/bootstrap.json`, `budget.json`, `order.json`, `parameters.json`, `deploy.sh`, the five `tower-app-*` stacks, and `infra/service/tower_infra`. Production was read only through the port's `GET /v1/deploy/status`. The session has no AWS credential, so "the template says" is all that is known of anything the status does not show.

## Verdict per resource

| Resource | Verdict | Note |
|---|---|---|
| Network (VPC, subnets, IGW, routes, S3 endpoint, security groups) | needed | Tasks are in public subnets with a public IP and no inbound rule; no NAT. The database is reachable only from the tasks' group. |
| RDS `tower-data`, db.t4g.medium, 20 GB gp3 | needed | Private, encrypted, deletion protection on, 7-day backups, single AZ. **No alarm** (fixed below). |
| ECS cluster `tower`, service `tower-service`, task definition (0.5 vCPU / 1024 MiB, ARM) | needed | Circuit breaker with rollback. **No alarm on task loss** (fixed below). The cluster still listed `FARGATE_SPOT`, a leftover (dropped). `TOWER_STANDBY_CLUSTER` is not one: the prune's cluster (`prune.py`), misnamed only. |
| Service ExecutionRole | needed | Least privilege. |
| Service TaskRole | **wrong/risky** | Grants the swap and prune of two Lambdas that left the stack (`tower-port-ack-ingress`, `tower-port-webhook-consumer`): anyone who later makes a function with that name has its code replaceable by the service. `bedrock-mantle:CreateInference` on `*`, live while the task sets `TOWER_API_MODELS`, is a spend exposure. |
| Port Lambda `tower-port-api`, HTTP API, alias `live` | needed | Authentication is in the app (bearer token checked by its sha256). Throttled at 10 rps. **No error, throttle or 5xx alarm** (fixed below); no access logs. |
| Bucket `tower-outputs-*` (stack `tower-app-runner`) | needed | Holds the Lambda zips and code bundles; TLS only, public access blocked. The `runs/` lifecycle rule and the runner parameters serve the dormant runner (D-316): kept. |
| ECS service `tower-runner` (seen in the status' ECS events) | **to check live** | No template defines it since 14/11 (it left `50-runner.json`). Either it is INACTIVE (deleted, still listed) or orphaned. It is a production change: `docs/process/host-swap-queue.md`. |
| CodeBuild `tower-infra-deploy`, doorbell Lambda + URL, EventBridge rules, deployer role | needed | The doorbell URL is public (AuthType NONE) and authenticated by its token, with no throttle and no error alarm. The bootstrap's defaults still name Origin (`origin.cursor.com`, `mod/roadmap-integration`): a re-apply with defaults would deploy Origin again. |
| Boundary `tower-boundary`, CFN exec role | needed, **risky** | The boundary's denies do not protect the alerting path (the alerts topic, the Torre's queue, the deploy logs). |
| SNS `tower-platform-events`, SQS `tower-alerts-torre` | needed, **risky** | The topic policy lets any principal of the account delete, rewire or subscribe to the topic. |
| ECR `tower-ingress` and every full build's ingress image | **dead** | No stack reads it since 14/11 (`2db2f6b`), yet each full build still builds and pushes it. |
| Deployer's read of `/aws/lambda/tower-port-webhooks` | dead | That function is gone. |
| Webhook queue `tower-port-webhooks` and its DLQ | gone from the templates (`2db2f6b`) | Nothing creates them; to confirm live with the runner's service. |

## The service's code paths
- **Started by `serve`:** the autodeploy, drill and prune threads; the dispatcher tick; the 30 s heartbeat (vitals, `stall.Watch`); the in-task heirs. The Origin looks (checks, observations, branches) are not started, as D-316 asks.
- **Dormant on purpose (D-316):** `forge`, `forge_webhooks`, `checks`, `observations`, `branches`, `ingress`, `webhook_consumer`, `runner`, `container`.
- **Dormant without a decision naming them:** the AI-session executors (`sessions`, `api_*`, `cli_sessions`, `cursor_agents`, the model clients) and `subscriptions`. They still run a query every second each (`sessions.follow`, the subscription delivery).
- **Wrong/risky:**
  - `canary.Live` fires runner canaries after a queue swap (below).
  - `stall.Watch` watches runner runs with no runner.
  - The autodeploy thread can die silently: the task stays healthy and stops deploying.
  - `deploy.base_branch` still defaults to the Origin branch.
  - `fastdeploy` still lists the two removed Lambdas.

## The finding that pages: every deploy's canary is red
A canary is one `container` job through dispatch, take and run. Only the runner takes it, and the runner has been at DesiredCount 0 since 13/11. The queue swap was designed to fire no runner canary, and the standby's watch and the autodeploy skip it, but `canary.Live.due()` does not. So after every swap the heir fires `swap:` and `reload:` canaries, each red after 120 s, each published to the alerts topic. All the canaries the status keeps are red, from 15/11 23:44 to now: a false alarm on every deploy, which hides a real one.

## Security, failure modes, observability, cost
- **Public exposure:** the API (app-authenticated, throttled) and the doorbell URL (token-authenticated, not throttled). Nothing else accepts traffic.
- **Least privilege:** the TaskRole's dead Lambda grants and Bedrock `*`, and the topic policy (above).
- **Observability:** there was no CloudWatch alarm at all. The only alert paths were the deploy's SNS messages, the EngineImpaired rule and the canary, and the canary pages falsely.
- **Cost** (the template's prices): RDS about US$49, Fargate and its public IP about US$15, CodeBuild per build (US$20 budget), the rest negligible. About US$65-70/month against the US$150 budget and the US$200 ceiling; the status estimates US$30 for November.

## The fixes
| Fix | Where | How it ships |
|---|---|---|
| CloudWatch alarms: service down and memory, database storage, memory, CPU and connections, port errors and throttles, API 5xx, to `tower-platform-events` (10 alarms, about US$1/month) | stacks 20, 30, 40 | PR with this document |
| The canary skips a queue swap and an in-task adoption, as the watch and the autodeploy do | `canary.py` | service PR |
| A dead autodeploy thread is said and started again | `autodeploy.py` | service PR |
| `deploy.base_branch` defaults to `main` | registry, `config_data.py`, `autodeploy.py` | service PR |
| `fastdeploy` and the TaskRole drop the two removed Lambdas | `fastdeploy.py`, stack 30 | service PR, then stack PR |
| The full build stops making the dead ingress image | `infra/ingress/Dockerfile` deleted (`deploy.sh` builds each `infra/*/Dockerfile`) | deployer PR |
| Stack leftovers: the cluster's `FARGATE_SPOT`, the database group's default allow-all egress | stacks 10, 30 | one PR |
| Topic policy, boundary denies for the alerting path, Origin defaults, doorbell concurrency and alarms, the dead log grant | bootstrap | applied by the Torre (16/11 06:20:44 UTC, change set req-aws-review; the DLQ alarm 17/11 17:50:22 UTC, req-dlq-alarm), mirrored with its hash |
| Bedrock grants and `TOWER_API_MODELS` | stack 30 | for Daniel to decide (spend) |
| The live `tower-runner` service, the webhook queue and its DLQ | production | to check with an AWS credential; `host-swap-queue.md` |
