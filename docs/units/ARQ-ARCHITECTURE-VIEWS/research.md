# ARQ-ARCHITECTURE-VIEWS — research

## Quem já resolveu

- [Structurizr DSL](https://docs.structurizr.com/dsl): descreve um modelo arquitetural do qual podem sair diferentes vistas, reduzindo repetição de elementos e relações.
- [Backstage, descritores de catálogo](https://backstage.io/docs/features/software-catalog/descriptor-format/): estrutura entidades e relações; distingue dados de entrada e relações produzidas pelo catálogo.
- [ArchUnit](https://www.archunit.org/userguide/html/000_Index.html): confronta restrições arquiteturais com dependências de código; oferece referência de prova além da consistência de um diagrama.

## Estado da arte

Modelo compartilhado reduz divergência entre vistas, mas coerência interna não demonstra fidelidade ao sistema. Catálogos dependem da qualidade dos fatos ingeridos; análise de código encontra relações do universo que consegue interpretar. O passo mais ambicioso combina vistas derivadas com verificação contra fatos observáveis. Ele exige delimitar quais relações são verificáveis e quais afirmações comportamentais precisam de outras provas. A pesquisa não encontrou motivo para tratar existência de um alvo como comprovação da garantia que a prosa atribui a ele.

## Encaixe em nós

O [intake](intake.md) remete a [F9/R6](../ARQ-SISTEMA/audit.md): dois leitores retirados ainda apareciam nas vistas, exigindo reconciliar ao menos 3 documentos, 4 com PORTS. É uma baseline histórica; o remendo documental da ARQ-SISTEMA já corrigiu relações conhecidas. O problema de continuidade é a ausência de vínculo que acompanhe a próxima retirada.

É aproveitável a separação modelo/vista do Structurizr; é adaptável a distinção entre fato declarado e relação derivada do Backstage. ArchUnit inspira confronto com implementação, sem ser adoção direta no engine Python/shell. Nenhuma dessas referências justifica migrar toda a documentação para uma DSL. A necessidade que emerge é saber quais fatos sustentam cada relação e qual limite a evidência tem, antes de escolher fonte, gerador ou recusa.

## Escada de ambição

O mínimo útil é distinguir nas vistas relações observadas, garantias e propostas, com seu alcance. Uma evolução possível é compartilhar fatos das relações repetidas, tornando visível sua procedência. Fonte verificável, vistas derivadas e recusa de alvo retirado são a ambição A2 herdada, condicionada ao universo e ao custo que a unidade vier a demonstrar. Auditoria e plano escolherão a intervenção; não fica fixado aqui modelo C4, DSL, gerador ou lista fechada de documentos.
