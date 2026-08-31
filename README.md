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
- `docs/releases/v1.2.md`: manifesto auditável, hashes e gates da release 1.2.
- `docs/releases/v1.2.1.md`: manifesto auditável de W06, do pin Odoo e da auditoria institucional de 2026/2.
- `docs/releases/v1.2.2.md`: manifesto da transição do plano para Markdown como formato único.
- `reproducibility/odoo-source.lock.json`: lock legível por máquina da fonte Odoo selecionada.
- `reproducibility/institutional-sources.lock.json`: hashes, requisitos e anomalias das fontes institucionais locais.
- `scripts/check_repository_safety.ps1`: verificação de caminhos proibidos e padrões de credenciais sem exibir o valor suspeito.
- `odoo-19.0/`: snapshot local ignorado pelo Git e usado somente para exploração; a reprodução usa o commit oficial fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`, e o digest OCI será registrado depois da construção da imagem correspondente.
- `relatorio_tcc_I_fci_pacote/`: pacote local ignorado, usado somente como evidência de continuidade e referência institucional; contém repositório aninhado e dados acadêmicos que não devem ser preparados para commit.

## Edição do plano

O plano-mestre é mantido somente em Markdown. Não há etapa de conversão para Word ou PDF. O artigo institucional será produzido separadamente sobre uma cópia saneada do template FCI vigente.

## Segurança e publicação de versões

Antes de preparar qualquer commit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
```

Depois de adicionar somente os caminhos pretendidos, executar novamente com `-StagedOnly`. Arquivos `.env`, chaves, tokens, dumps, dados reais, logs brutos e o snapshot local do Odoo não podem ser versionados. Cada versão publicada do plano corresponde a um commit dedicado com o Markdown, decisões, changelog e manifesto; o procedimento completo está em `AGENTS.md`.

Os dados brutos dos experimentos permanecem fora do Git em armazenamento criptografado e com cópia imutável. O repositório deve conter somente o manifesto saneado de hashes, schema, proveniência e retenção, além dos exports sintéticos aprovados para publicação.

O documento é um plano de execução, não o artigo final. O edital e o template de 2026/2 já foram auditados: o produto institucional será um artigo separado de 10–20 páginas, submetido inicialmente no Oriente entre 03 e 09/11/2026. As lacunas residuais estão listadas em `docs/institutional-requirements.md`.
