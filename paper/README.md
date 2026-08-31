# Artigo institucional do TCC II

Este diretório contém a fonte editável do artigo científico estendido destinado à submissão do TCC II no Oriente. Ele é separado do plano-mestre e segue DEC-019.

## Estado atual

A versão corrente é **pré-experimental**. Ela registra resultados técnicos comprovados de M1/M2 e a metodologia congelável, mas não apresenta ASR, BTSR, UACR, SDR, latência ou custo confirmatórios porque C1, piloto, freeze e execução principal ainda estão pendentes.

O PDF gerado agora serve para revisão científica, editorial e de template com o grupo e o orientador. Não deve ser tratado como arquivo final de submissão.

## Arquivos

- `main.tex`: layout, metadados, autoria e composição do artigo;
- `sections/`: Resumo, Abstract e seções 1–5;
- `referencias.bib`: somente fontes efetivamente citadas;
- `assets/fci-header.png`: asset institucional saneado, reaproveitado do pacote auditado;
- `build.ps1`: compilação isolada em `.runtime/paper-build`;
- `validate_paper.ps1`: páginas, resumos, títulos, metadados, placeholders e reconciliação citação↔referência;
- `validation-report.json`: resultado auditável dos gates automáticos e da inspeção visual da compilação corrente;
- `SUBMISSION_CHECKLIST.md`: gates já atendidos e pendências que bloqueiam o envio;
- `relatorio_tcc_ii.pdf`: PDF compilado e validado, quando presente.

## Compilação

Pré-requisitos: MiKTeX com `pdflatex`, `bibtex`, `pdfinfo` e `pdftotext`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\paper\build.ps1
```

Arquivos auxiliares e logs ficam em `.runtime`, fora do Git. O script copia para este diretório somente o PDF final e executa a validação automaticamente.

A compilação validada em 31/08/2026 possui 17 páginas, Resumo com 217 palavras, Abstract com 205 palavras e 20 citações reconciliadas com 20 referências. O log final não contém caixas acima ou abaixo da largura, citações indefinidas ou referências pendentes. Os valores e o hash exato do PDF estão em `validation-report.json`.

Para validar um PDF já existente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\paper\validate_paper.ps1
```

## Origem editorial

O layout foi reconstruído e comparado com o template FCI 2026 auditado:

- `.doc` institucional: SHA-256 `56cb33c40e6c3d43ce809ba95999d04700da420db526bbc1e84ec627bb579945`;
- PDF de referência: SHA-256 `18b5802047437639edf0bcd5e2cfbfa15106bf6c9d2bb4ad406e71ad1435074b`.

O PDF original possuía título e autor de metadados não relacionados ao TCC. Esses valores não foram copiados. E-mails e identificadores acadêmicos do pacote local também não foram importados.

## Antes da submissão

O artigo final deverá substituir as declarações “não executado” pelos resultados reais, com denominadores, missing, efeitos e IC95%. Também será necessário confirmar a extensão aceita pelo Oriente, contatos, política de IA, aprovação do orientador e aderência visual final ao arquivo disponibilizado na tarefa vigente. Consulte `SUBMISSION_CHECKLIST.md`.
