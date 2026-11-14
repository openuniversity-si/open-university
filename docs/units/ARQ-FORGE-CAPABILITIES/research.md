# ARQ-FORGE-CAPABILITIES — research

## Quem já resolveu

- [pluggy](https://pluggy.readthedocs.io/en/stable/): separa especificações e implementações de hooks e oferece verificação de pendências; hooks opcionais mostram que extensão registrada não significa presença de toda operação.
- [Python, abc](https://docs.python.org/3/library/abc.html): impede instanciar classes concretas com métodos abstratos pendentes, antecipando parte da verificação de interface.
- [Stevedore, padrões de habilitação](https://docs.openstack.org/stevedore/latest/user/patterns_enabling.html): distingue descobrir plugins de habilitá-los, inclusive por seleção explícita.

## Estado da arte

As referências separam descoberta, seleção e conformidade de interface. Interfaces abstratas detectam ausência estrutural cedo, mas não demonstram comportamento equivalente; hooks permitem extensão parcial, cujo caráter obrigatório precisa ser declarado. Habilitação explícita escolhe o plugin, sem provar que ele atende ao fluxo. A síntese aplicável é avaliar compatibilidade no contexto de uso e distinguir presença de método de garantia operacional. Isso requer conhecer consumidores e obrigações; uma interface universal pode exigir capacidades desnecessárias.

## Encaixe em nós

O [intake](intake.md) usa [F6/R3 da auditoria](../ARQ-SISTEMA/audit.md): 24 métodos públicos no GitHub contra 9 no Origin e 13 exceções externas autorizadas. A diferença de superfície não significa que cada fluxo precise dos 24 métodos. A matriz herdada contextualiza consumidores; não certifica todos eles nem autoriza selecionar Origin.

É aproveitável separar seleção e conformidade; é adaptável a ideia de obrigações explícitas por uso. Substituir a porta por pluggy ou por uma hierarquia abc não se justifica pelas referências: nenhuma elimina os acessos GitHub fora do adaptador. A pesquisa indica que requisitos do consumidor e situação de migração são dimensões distintas. O tratamento das 13 exceções depende de entender por que cada acesso permanece, sem presumir remoção indiscriminada ou perpetuação do baseline.

## Escada de ambição

O primeiro degrau útil é explicitar o alcance e as limitações da compatibilidade já documentada. Depois cabe aprofundar os requisitos efetivos por consumidor e a razão das exceções, distinguindo operação disponível, exigida e comprovada. A2 aponta a ambição de recusar seleção incompatível na construção do fluxo; a forma dessa fronteira e o destino das exceções ficam para auditoria e plano próprios. Esta pesquisa não prescreve novas portas, troca de adaptador ou cronograma de migração.
