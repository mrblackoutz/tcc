# TCC — Arquitetura de proteção na integração de LLMs em ERPs

Este repositório contém o plano-mestre editável do TCC em Ciência da Computação sobre mitigação de prompt injection indireta em um fluxo de Contas a Pagar integrado ao Odoo 19.0 Community self-hosted.

## Artefatos principais

- `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md`: fonte editorial e operacional.
- `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.docx` e `.pdf`: artefatos históricos da v1.2.1; não representam a versão corrente.
- `validate_tcc_docx.ps1`: validador histórico usado na auditoria da v1.2.1; não faz parte do fluxo atual.
- `AGENTS.md`: regras obrigatórias de execução, versionamento, decisões e proteção de dados.
- `CHANGELOG.md`: histórico das versões publicadas do plano-mestre.
- `docs/decision-log.md`: decisões surgidas durante a construção.
- `docs/deviation-log.md`: divergências depois do congelamento experimental.
- `docs/institutional-requirements.md`: matriz de conformidade com edital, template, calendário e avaliação do TCC II 2026/2.
- `docs/lab-runbook.md`: procedimento operacional dos marcos M1–M2, evidências, recuperação e limites.
- `docs/m2-c0-baseline.md`: relatório técnico, interpretação e limites científicos do vertical slice M2/C0.
- `docs/releases/v1.2.md`: manifesto auditável, hashes e gates da release 1.2.
- `docs/releases/v1.2.1.md`: manifesto auditável de W06, do pin Odoo e da auditoria institucional de 2026/2.
- `docs/releases/v1.2.2.md`: manifesto da transição do plano para Markdown como formato único.
- `docs/releases/v1.2.3.md` e `docs/releases/v1.2.4.md`: manifests históricos da correção JSON-2 e do scaffold inicial do laboratório.
- `docs/releases/v1.2.5.md`: manifesto do aceite técnico M1 corrigido conforme DEC-016.
- `docs/releases/v1.2.6.md`: manifesto do aceite técnico M2/G2 e de seus limites pré-experimentais conforme DEC-017.
- `reproducibility/odoo-source.lock.json`: lock legível por máquina da fonte Odoo selecionada.
- `reproducibility/lab-environment.lock.json`: versões, digests e últimos aceites M1/M2 saneados do laboratório.
- `reproducibility/institutional-sources.lock.json`: hashes, requisitos e anomalias das fontes institucionais locais.
- `scripts/check_repository_safety.ps1`: verificação de caminhos proibidos e padrões de credenciais sem exibir o valor suspeito.
- `odoo-19.0/`: snapshot local ignorado pelo Git e usado somente para exploração; o build usa a origem oficial no commit fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`, e o manifest OCI aceito está registrado nos locks.
- `relatorio_tcc_I_fci_pacote/`: pacote local ignorado, usado somente como evidência de continuidade e referência institucional; contém repositório aninhado e dados acadêmicos que não devem ser preparados para commit.

## Estado executável

O marco M1 foi validado em 31/08/2026, ainda antes do congelamento experimental. O laboratório constrói Odoo 19.0 Community a partir do commit fixado, sobe PostgreSQL 18 em rede interna, usa uma identidade C0 dedicada e executa por JSON-2 a criação e a remoção de exatamente uma conta de fornecedor sintética em rascunho. A conta mantém a referência bancária e a ligação com a linha de um pedido de compra confirmado; o hash canônico após a remoção coincide com o estado inicial.

O marco M2 também foi validado em 31/08/2026. Ele gera localmente um PDF sintético benigno com camada de texto, extrai o conteúdo sem OCR, produz uma proposta tipada validada por JSON Schema, resolve as referências por chaves de negócio e cria o mesmo rascunho via executor direto C0. Foram aprovados 41 testes e o hash após a remoção voltou ao estado inicial.

M2 é uma baseline de desenvolvimento do encanamento, não o C0 científico: o adaptador `deterministic-development/v1` não usa LLM e está proibido nas runs experimentais. Os aceites ainda não incluem modelo LLM, prompt injection, C1, add-on de autorização, postagem ou pagamento. O manifesto OCI é local e não foi publicado em registry. O estado verificável corrente está em `reproducibility/lab-environment.lock.json`; PDF, credenciais e evidências detalhadas permanecem em `.runtime`, fora do Git.

## Execução local de M1 e M2

Pré-requisitos: PowerShell, Git, Docker Desktop em modo Linux/AMD64, Docker Compose e acesso de rede no primeiro build.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1
```

O primeiro comando gera credenciais locais aleatórias sem exibi-las. O segundo revalida M1, cria um builder isolado, exporta a mesma resolução em formatos OCI e Docker, verifica manifest, config, labels e commit interno, executa 41 testes, carrega as fixtures sintéticas e roda os smokes M1/M2. Ao terminar, os contêineres são encerrados e os volumes são preservados. Para executar somente M1, use `scripts/smoke_test.ps1`.

Não use `new_local_env.ps1 -Force` com um banco existente sem planejar a rotação conjunta do volume. A opção `smoke_test.ps1 -RecreateVolumes` remove somente os volumes rotulados do projeto, mas é destrutiva e exige autorização explícita do operador. O procedimento completo e os critérios de diagnóstico estão em `docs/lab-runbook.md`.

## Edição do plano

O plano-mestre é mantido somente em Markdown. Não há etapa de conversão para Word ou PDF. O artigo institucional será produzido separadamente sobre uma cópia saneada do template FCI vigente.

## Segurança e publicação de versões

Antes de preparar qualquer commit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
```

Depois de adicionar somente os caminhos pretendidos, executar novamente com `-StagedOnly`. Arquivos `.env`, `.runtime`, chaves, tokens, dumps, dados reais, logs brutos, exports locais de imagem e o snapshot local do Odoo não podem ser versionados. Cada versão publicada do plano corresponde a um commit dedicado com o Markdown, decisões, changelog e manifesto; o procedimento completo está em `AGENTS.md`.

Os dados brutos dos experimentos permanecem fora do Git em armazenamento criptografado e com cópia imutável. O repositório deve conter somente o manifesto saneado de hashes, schema, proveniência e retenção, além dos exports sintéticos aprovados para publicação.

O documento é um plano de execução, não o artigo final. O edital e o template de 2026/2 já foram auditados: o produto institucional será um artigo separado de 10–20 páginas, submetido inicialmente no Oriente entre 03 e 09/11/2026. As lacunas residuais estão listadas em `docs/institutional-requirements.md`.
