# Artigo institucional do TCC II

Este diretório contém a fonte editável do artigo científico estendido destinado à submissão do TCC II no Oriente. Ele é separado do plano-mestre e segue a [decisão sobre o artigo institucional (DEC-019)](../docs/decision-log.md#dec-019).

## Estado atual

A versão corrente é **pré-experimental**. Ela registra resultados técnicos comprovados de M1/M2 e a metodologia congelável, mas não apresenta taxas de sucesso do ataque, sucesso benigno, ações críticas indevidas, latência ou custo confirmatórios porque C1, piloto, freeze e execução principal ainda estão pendentes.

A revisão de 08/09/2026 retira a exposição de dados e mantém 90 pares distribuídos igualmente entre os três objetivos financeiros. Perguntas e hipóteses possuem links internos no PDF. O registro está na [decisão de redução do escopo (DEC-023)](../docs/decision-log.md#dec-023).

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

A compilação revisada em 08/09/2026 possui 17 páginas, Resumo com 211 palavras, Abstract com 196 palavras e 20 citações reconciliadas com 20 referências. O log final não contém caixas acima ou abaixo da largura, citações indefinidas ou referências pendentes. Os valores e o hash exato do PDF estão em `validation-report.json`.

A compilação desta revisão usou TeX Live 2025 no WSL. O pacote ABNT foi obtido do pacote oficial Ubuntu `texlive-publishers` e extraído em diretório temporário; nenhuma configuração do laboratório experimental foi alterada. A sequência é pdfLaTeX, BibTeX no diretório de saída e mais duas passagens de pdfLaTeX, com `TEXINPUTS`, `BIBINPUTS` e `BSTINPUTS` apontando para fonte e estilos. As versões e os hashes usados estão no relatório de validação.

Com Python e Poppler disponíveis no WSL/Linux, a verificação de documentação e artigo pode ser executada a partir da raiz:

```bash
python3 scripts/validate_current_docs.py --paper-pdf paper/relatorio_tcc_ii.pdf --paper-log /caminho/do/build/main.log
```

O log precisa ser da mesma compilação do PDF. A inspeção visual continua obrigatória e é registrada separadamente.

Para validar um PDF já existente no Windows:

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
