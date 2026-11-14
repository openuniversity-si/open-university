# engine-forge-origin — research

## Quem já resolveu
GitHub Apps mint an installation token from a JWT. Origin does the same with EdDSA, audience `origin-apps`, and `POST /v1/origin/app/installations/{id}/access_tokens`, returning an `oit_` token of at most 15 minutes. GitHub commit statuses are Origin check runs: `POST /v1/origin/repos/{owner}/{repo}/check-runs` (installation token, scope `repository:checks:write`). The Origin CLI (`origin api`) is a user-token client; this adapter speaks REST so the flow does not shell out.

## Estado da arte
A forge port with one adapter per vendor, selected by configuration. Check runs are the verdict a pull request shows. The narrow port (six operations) is what makes the second vendor cheap. That is FORGE-PORT, already merged.

## Encaixe em nós
The port, the GitHub adapter and the contract suite exist. This unit adds the client, registers `origin`, and runs the same six operations and the same flow function under both keys. The host and the Origin slug are registry values (`forge-events.origin_api_base`, `forge-events.origin_repo`).

## Escada de ambição
1. Origin is selectable and the contract passes on a fake client.
2. An operator sets the key to `origin` with an app key or an `oit_` token, and the gate's verdict is a real check run.
3. The thirteen baseline sites move behind the port, and the default of the key becomes `origin`.
