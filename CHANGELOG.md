# Changelog do plano-mestre

Este arquivo registra versões publicadas do plano. Cada versão, a partir de 1.2, deve corresponder a um commit Git dedicado contendo a fonte normativa, decisões, changelog e manifesto aplicáveis.

## [1.2.8] — 2026-09-01

- fixada em DEC-020 a fronteira mínima de egress: Odoo, banco e gateway permanecem sem saída externa; um `llm-client` dedicado acessará o DeepSeek somente por proxy TLS com destino permitido e o Ollama somente pela rede interna;
- implementados no gateway 0.3.0 os adapters DeepSeek/Ollama, configuração segura, schema auxiliar de saída do modelo, injeção de proveniência confiável pelo adapter e sanitização de erros e metadados;
- aprovados 82 testes em contêiner `--network none` e somente leitura, sem chamada a API, download de modelo, leitura ou criação de chave; o ID local da imagem foi registrado sem tratá-lo como digest de manifest OCI;
- atribuídos em DEC-021 os workstreams: Felipe em ciência/dados, Thomaz em arquitetura/segurança e Gustavo em Odoo/experimentação, com revisão cruzada e fronteiras de integração explícitas;
- publicado `docs/task-backlog.md` com 116 tarefas identificadas, prioridade, proprietário, revisor, dependências, entregável, Definition of Done, estado e ondas W0–W7 para execução paralela;
- atualizado o controle institucional com os papéis e o proprietário operacional do cadastro/requerimento, preservando como pendentes a confirmação externa e o recibo;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem de não inferioridade, threat model, amostras e comparação pareada C0/C1;
- permanecem pendentes G3b (topologia e testes negativos de egress), G3c (smokes reais autorizados), competência do C0 científico, C1, dataset, piloto, freeze e resultados.

## [1.2.7] — 2026-08-31

- registrada em DEC-018 a seleção do DeepSeek por API como modelo principal e do Qwen3 14B quantizado via Ollama como segundo bloco separado de robustez e transportabilidade;
- corrigida a nomenclatura de reprodução: a API recebe `deepseek-v4-flash`, associado pelo provedor em 31/08/2026 a `DeepSeek-V4-Flash-0731`, sem tratar o alias móvel como snapshot imutável;
- fixada a tag local explícita `qwen3:14b-q4_K_M`, mantendo pendentes manifest completo, digests de blobs, download autorizado e smoke de hardware;
- definido *thinking* desligado no núcleo dos dois modelos e preservada a igualdade de modelo, prompt, schema, parâmetros e retries entre C0 e C1 dentro de cada bloco;
- preservadas a meta principal pré-piloto de 180 documentos e 1.080 runs e a amostra secundária de 72 documentos e 432 runs; a menção exploratória a 120 documentos não alterou W05;
- acrescentados protocolo operacional de seleção e lock de proveniência, incluindo captura temporal de alias/backend, request ID saneado, hashes, tokens, custo, latência, erros e retries;
- registrada a viabilidade local ainda condicional: Ollama 0.30.10, RTX 3060 Ti de 8 GiB, Qwen de catálogo com aproximadamente 9,3 GB e necessidade de offload e benchmark antes do bloco secundário;
- mantida a rede interna do laboratório sem egress amplo; o desenho de saída mínima e a implementação dos adapters permanecem pendentes para G3;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem de não inferioridade, threat model, dataset planejado e comparação C0/C1.

## [1.2.6] — 2026-08-31

- registrada em DEC-017 a separação entre o vertical slice pré-experimental M2 e o futuro C0 científico baseado em LLM;
- comprovado o fluxo PDF sintético benigno com camada de texto → extração sem OCR → proposta `vendor-bill-proposal/v1` → execução direta C0 → conta de fornecedor em rascunho → restauração do estado;
- implementados limites de ingestão, validação estrita por JSON Schema, reconciliação decimal e resolução de referências exclusivamente por chaves de negócio sintéticas;
- fixado `deterministic-development/v1` como adaptador somente de desenvolvimento, explicitamente proibido nas runs científicas;
- ampliada a suíte do gateway de 19 para 41 testes, incluindo PDFs criptografados/sem texto/inválidos, campos duplicados ou ausentes, schema incompatível, totais divergentes e estados residuais;
- aceito o smoke `M2-BENIGN-001` com hashes próprios do PDF, texto, proposta, estado criado e estado restaurado, preservando os volumes;
- atualizado o gateway para 0.2.0, com dependências diretas e transitivas resolvidas, config digest local e hashes de build registrados no lock;
- marcado M2/G2 como atendido tecnicamente, mantendo pendentes para o piloto/G3 a implementação e a seleção do LLM, a competência benigna do C0 científico e o dataset piloto;
- mantidos inalterados problema, hipóteses, endpoints, métricas, margem, threat model, dataset planejado e desenho experimental C0/C1.

## [1.2.5] — 2026-08-31

- preservada a v1.2.4 como scaffold histórico e incorporada a correção de aceite registrada em DEC-016, sem reescrever commits ou manifesto anteriores;
- comprovado o manifest OCI local da imagem Odoo (`sha256:3e0bcf8e796820e89577b1db24b4dbb54a63669f66384c4b61577068adf1f392`) como objeto distinto do config digest efetivamente carregado;
- sincronizados os locks de fonte e ambiente com commit, plataforma, imagem-base, manifest, config, labels e evidência interna de revisão;
- substituído o smoke administrativo de cadastro por identidade C0 dedicada e por fixtures sintéticas de empresa, fornecedor, banco, produto e pedido de compra confirmado;
- comprovadas via JSON-2 a criação e leitura de uma única conta de fornecedor em rascunho, a persistência do beneficiário, a ligação com a linha de compra e a remoção com restauração exata do hash inicial;
- classificado como atendido o marco técnico M1, sem declarar concluídas as obrigações não técnicas de G1 ou os marcos M2/C0, C1, dataset, piloto e freeze;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset planejado e desenho experimental C0/C1.

## [1.2.4] — 2026-08-31

- implementado o primeiro incremento executável do laboratório M1/G1 conforme DEC-014 e DEC-015;
- construída a imagem Docker do Odoo 19.0 Community a partir do commit imutável `a4b877245c9cb5e3d7152d1593a518170f115ca1` com labels OCI e evidência interna verificada;
- adotado PostgreSQL 18 (`postgres:18@sha256:7341002d2b8c7c5bdd7542a671a95b36196c0b5b888daf454ae4fc33ba5346d7`) com volume configurado para a estrutura de diretórios 18+;
- implementado o pacote de gateway JSON-2 (`tcc_gateway`) com sanitização de credenciais em logs/erros, serialização canônica UTF-8/SHA-256 e 19 testes unitários aprovados;
- implementados scripts operacionais de bootstrap (`new_local_env.ps1`), build (`build_odoo_image.ps1`) e smoke test determinístico (`smoke_test.ps1`, `smoke_test_gateway.py`) com ciclo completo de criação/leitura de fornecedor e reset comprovado por volumes;
- atualizados `reproducibility/lab-environment.lock.json` com os digests e metadados imutáveis;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset e desenho C0/C1.

## [1.2.3] — 2026-08-31

- corrigida, conforme DEC-013, a garantia técnica da fronteira JSON-2 antes do início da implementação;
- registrado que o controller consome `context` antes de chamar o método e que o executor deve neutralizar sua influência e comprovar invariância, em vez de alegar rejeição literal;
- reformulado o menor privilégio de C1 como ausência de mutações críticas fora de `ap.security.executor.execute`, com inventário explícito de eventuais leituras residuais das ACLs básicas;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset e desenho C0/C1.

## [1.2.2] — 2026-08-31

- adotado o Markdown como único formato editável e corrente do plano-mestre, conforme DEC-012;
- removido `build_tcc_docx.ps1` e encerrada a geração obrigatória de DOCX/PDF do plano;
- preservados DOCX, PDF, validador e manifests anteriores apenas como evidência histórica da v1.2.1;
- mantido o artigo institucional como artefato separado no template FCI, sem mudança no escopo científico ou no experimento;
- atualizados fluxo de releases, gates e árvore sugerida do repositório para eliminar a dependência do Microsoft Word.

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
