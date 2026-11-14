# ARQ-SISTEMA — research

## Quem já resolveu

- [C4, Simon Brown](https://c4model.com/): descreve contexto, contêineres, componentes e código; exige identificar elementos e relações reais, sem confundir níveis de abstração.
- [arc42](https://arc42.org/overview/): organiza contexto, blocos, cenários de execução e decisões; exige selecionar as vistas úteis e mantê-las coerentes, em vez de preencher um template inteiro por obrigação.
- [ADR](https://adr.github.io/): registra uma decisão, suas razões e consequências; exige vincular a escolha ao contexto, mas não substitui a descrição do sistema existente.
- [Contextos delimitados, DDD, explicado por Martin Fowler](https://martinfowler.com/bliki/BoundedContext.html): separa modelos e linguagens e explicita suas relações; exige descobrir onde o mesmo termo tem sentidos diferentes antes de traçar fronteiras.
- [Import Linter](https://import-linter.readthedocs.io/en/stable/): transforma dependências permitidas e proibidas entre módulos Python em contratos executáveis; exige módulos identificáveis e regras explícitas, e só verifica o que aparece no grafo de imports.

## Estado da arte

A solução de referência combina descrição estática em níveis (C4), cenários que mostram quem faz o quê em execução (arc42), fronteiras semânticas e relações entre contextos (DDD), e razões das escolhas (ADR). O hoje precisa de evidência ligada a uma revisão do código; o ideal precisa declarar objetivos e compromissos, separado do observado. Um desenho não decide sozinho se duas operações semelhantes são duplicação indevida ou responsabilidades legítimas em contextos distintos.

O patamar mais avançado deste recorte liga fronteiras declaradas a contratos executáveis: uma dependência proibida causa recusa automática. Isso exige regras com exemplos permitidos e violações demonstráveis. Import Linter exemplifica a técnica, mas imports corretos não provam exclusividade de operação: duas implementações independentes podem executar a mesma responsabilidade sem importar uma à outra. Essa propriedade exige evidência e verificações além do grafo estático.

## Encaixe em nós

Copiar a separação entre vistas de contexto, componentes e execução; adaptar a nomenclatura C4 ao motor, sem chamar cada script de sistema nem cada unidade de contexto. Usar arc42 como seleção de vistas para descrever hoje e ideal, não como novo documento obrigatório com todas as seções. Adaptar DDD para distinguir responsabilidade e vocabulário de organização de arquivos: a fronteira precisa dizer quem realiza cada operação e como os demais a solicitam.

ADR não é uma lacuna: [DECISIONS.md](../../domain/DECISIONS.md) já registra decisões com provas lidas por `scripts/lib/structure.py`; cabe relacioná-las à descrição, sem criar outro registro. [PORTS.md](../../architecture/PORTS.md) inclui adaptadores, slots futuros e proibições: não basta como inventário operacional. O catálogo de vendedores reúne nove entradas, duas ativas, seis slots e uma proibida; isso não equivale à quantidade de portas da tabela. [UNITS.md](../../architecture/UNITS.md) define contrato, dono e bateria, mas o intake reconferiu 47 manifestos com o mesmo dono e somente 5 com bateria declarada; esses campos não demonstram fronteiras efetivas de operação.

Adaptar o princípio do Import Linter ao mecanismo existente: `structure-check`, `unit_check.py` e `commit_check.py` já recusam violações nos hooks e no gate. Não cabe instalar uma ferramenta por antecipação nem usar GitHub Actions. A lacuna específica é verificar responsabilidade cruzada, não inventar outro ponto de recusa; a cobertura das regras atuais sobre operações ainda precisa de observação. As cinco referências bastam neste recorte: descrição, semântica, decisão e verificação; catálogo de ferramentas e reorganização de equipes ampliariam a pesquisa sem estabelecer o hoje.

## Escada de ambição

1. **Mínimo útil:** descrição verificável do sistema existente após o marco Origin do intake, com revisão identificada, universo explícito de componentes e operações, relações, responsáveis observados e sobreposições evidenciadas ou lacunas assumidas. É a base de comparação; não escolhe o desenho-alvo nem elimina componentes.
2. Descrição do ideal separada do hoje, com objetivos, fronteiras de responsabilidade e compromissos explícitos; diferenças e duplicações justificadas ficam vinculadas às decisões existentes ou posteriores.
3. Fronteiras verificadas nos hooks e no gate, com provas de recusa para dependências e operações proibidas e de aceitação para interações legítimas; as vistas e as regras evoluem juntas. O avanço depende do que a auditoria demonstrar e das alternativas que o plano comparar, não de uma ferramenta escolhida nesta abertura.

Premises: none
