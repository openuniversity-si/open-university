# ARQ-OPERATIONS — research

## Quem já resolveu

- [Backstage, descritores de catálogo](https://backstage.io/docs/features/software-catalog/descriptor-format/): representa componentes, APIs, donos e relações; torna a responsabilidade consultável, sem provar exclusividade de implementação.
- [Open Policy Agent](https://www.openpolicyagent.org/docs): separa política de decisão e aplicação; permite avaliar regras sobre dados apresentados pelo integrador.
- [ArchUnit](https://www.archunit.org/userguide/html/000_Index.html): testa dependências e restrições arquiteturais no código Java, aproximando regra declarada de recusa executável.

## Estado da arte

As referências mostram camadas complementares: catálogo dá vocabulário e dono; política decide sobre fatos; testes de arquitetura confrontam relações com implementação. Um catálogo depende de manutenção e não descobre operações ocultas. Política só conhece os dados recebidos. ArchUnit depende de código analisável no seu ecossistema. A combinação pode sustentar exclusividade verificável, mas nenhuma referência estabelece sozinha o censo semântico de operações deste engine. Essa é uma síntese da pesquisa, não uma solução já selecionada.

## Encaixe em nós

O [intake](intake.md) parte dos 47 manifestos e dos 20/29 commits multiunidade medidos em [ARQ-SISTEMA, F1–F3/R1](../ARQ-SISTEMA/audit.md); os números justificam investigar responsabilidade, não presumir que todo cruzamento é defeito. É aproveitável a distinção do Backstage entre componente, API e dono. A avaliação de políticas merece adaptação aos fatos que conseguirmos observar. ArchUnit serve de referência de recusa, mas sua implementação Java não se transfere diretamente ao engine Python/shell. Não há evidência para instalar um portal ou reorganizar módulos agora.

A pesquisa aponta como necessidade entender o que contamos como operação e qual evidência permite atribuir responsabilidade. O mapa parcial herdado não dá denominador global nem prova de exclusividade; um contrato sem esse fundamento apenas formalizaria a lacuna.

## Escada de ambição

O menor degrau útil é tornar explícitos o vocabulário operacional e o alcance do mapa disponível. Um degrau seguinte pode relacionar operações observadas, responsabilidades e consumidores, expondo desconhecidos. A ambição de censo completo e contrato recusante A2, herdada do plano, só ganha desenho e alvo quando houver evidência de cobertura e custo. A auditoria e o plano da unidade permanecem independentes; esta escada não fixa schema, ferramenta ou nova divisão de unidades.
