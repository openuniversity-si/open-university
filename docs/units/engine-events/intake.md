# engine-events — intake
## Pedido
Daniel, 2026-11-02: remove the two remaining forge-shaped GitHub sites in premises and idea-to-production through the existing port.
## Intenção
Keep provider representation inside adapters and product selection inside consumers.
## Contexto
Base 6017c0f52 exposes 22 operations. change_files already exists; historical merged listing does not.
## Regras
D-283, D-285, D-077, D-081. Draft PR, merge train only; no production writes. Premises: none.
## Problema real
Two forge reads bypass the port; success is zero such sites and equivalent consumer behavior with shared adapter evidence.
## Lacunas
Origin remote availability and actual server filtering are not established by offline evidence.
