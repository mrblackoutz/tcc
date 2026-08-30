# Changelog do plano-mestre

Este arquivo registra versões publicadas do plano. Cada versão, a partir de 1.2, deve corresponder a um commit Git dedicado contendo a fonte e os artefatos gerados.

## [1.2] — 2026-08-30

- adotado Odoo 19.0 Community self-hosted; SaaS 19.4, Enterprise e IA nativa ficaram fora do escopo;
- incorporados a base conceitual, o método, as limitações e os trabalhos futuros efetivamente desenvolvidos no TCC I;
- definido JSON-2 como transporte e o add-on transacional/idempotente como fronteira de autorização de C1;
- esclarecidas as decisões W03, W04, W06 e W07;
- detalhados ameaça, executor, identidade restrita, dataset, métricas, freeze, reexecução e validade confirmatória;
- instituídos `AGENTS.md`, logs de decisão/desvio, proteção de segredos, varredura pré-commit e um commit por versão;
- definido gate de artefatos sem metadados pessoais, revisões, macros ou objetos incorporados e custódia externa verificável dos dados brutos;
- ampliados `.gitignore` e o verificador local para credenciais, configurações sensíveis, JWT, cabeçalhos Bearer, URIs de banco autenticadas e arquivos de uma única linha;
- corrigido o gerador para impedir vazamento de estilo de código inline para a prosa;
- regenerados e validados Markdown, DOCX e PDF.

## [1.1] — 2026-08-28

- adotado o título proposto pelo orientador, sem alterar problema ou desenho experimental.

## [1.0] — 2026-08-26

- consolidado o primeiro plano operacional completo de pesquisa, implementação e avaliação experimental.

> As versões 1.0 e 1.1 foram produzidas antes da política de commit por versão. O histórico interno foi preservado no plano-mestre; a política passa a ser obrigatória a partir da versão 1.2.
