# Changelog do plano-mestre

Este arquivo registra versões publicadas do plano. Cada versão, a partir de 1.2, deve corresponder a um commit Git dedicado contendo a fonte e os artefatos gerados.

## [1.2.1] — 2026-08-30

- confirmada W06: margem de não inferioridade fixa de 10 pontos percentuais para `BTSR_C1 − BTSR_C0`;
- promovida a margem confirmatória a D13, antes do piloto e do teste final;
- fixada a fonte do Odoo em `https://github.com/odoo/odoo.git`, branch observada `19.0`, commit `a4b877245c9cb5e3d7152d1593a518170f115ca1`;
- registrado que o branch avançou após a seleção e que isso não altera o pin imutável aprovado;
- separado o commit Git do digest OCI, que será preenchido somente após construir a imagem desse commit;
- auditados o edital `EditalTCC_2026_2-V1`, o template FCI criado em 15/08/2026 e o fonte editável do TCC I;
- confirmados os três autores e Mario Olimpio de Menezes como orientador;
- definido que o plano permanece operacional e o produto institucional será um artigo separado de 10–20 páginas no template 2026, com submissão inicial até 09/11/2026;
- reancorado o cronograma, mapeadas as seções científicas para a estrutura oficial e acrescentados os gates de Resumo/Abstract, NBR 6023:2018, apresentação e excelência;
- confirmado que não haverá participantes humanos e que a nomenclatura DSR com experimento controlado permanece;
- mantido fora do Git o pacote local com repositório aninhado e PII, registrando apenas requisitos saneados e hashes;
- ampliado o verificador de segurança para bloquear o pacote institucional/TCC I mesmo em preparação forçada e detectar e-mail, CPF e identificadores acadêmicos em arquivos textuais;
- adicionados locks de procedência e manifesto auditável da release 1.2.1;
- regenerados e validados Markdown, DOCX e PDF.

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
- corrigida a paginação de tabelas longas para evitar uma última linha órfã antes de novo capítulo;
- criado manifesto auditável e commit-âncora da v1.2, sem reescrever os commits já publicados fora do padrão de release.
- regenerados e validados Markdown, DOCX e PDF.

## [1.1] — 2026-08-28

- adotado o título proposto pelo orientador, sem alterar problema ou desenho experimental.

## [1.0] — 2026-08-26

- consolidado o primeiro plano operacional completo de pesquisa, implementação e avaliação experimental.

> As versões 1.0 e 1.1 foram produzidas antes da política de commit por versão. O histórico interno foi preservado no plano-mestre; a política passa a ser obrigatória a partir da versão 1.2.
