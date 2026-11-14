# engine-events — research
## Quem já resolveu
- GitHub REST list pull requests: the current github_api reader already requests state=closed and paginates.
- Origin official OpenAPI, local /tmp/origin13-openapi.yaml, GET /v1/origin/repos/{ownerSlug}/{repoName}/pulls: cursor pagination and inclusive mergedSince.
- Existing forge_requirements and operation_demands: unsupported surfaces and unproved behavior refuse by name.
## Estado da arte
A provider-neutral read returns number, body and merge instant; adapters retain provider order and consumers sort when necessary. Shared contract tests compare observable behavior.
## Encaixe em nós
Reuse GitHub _pages, Origin _pages, and existing dispatch and evidence checks. No new write operation or transport is required.
## Escada de ambição
0: direct provider read. 1: existing change_files plus one shared closed_changes contract. 2: independent live server evidence, requiring a working Origin session.
