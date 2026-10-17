# Artigo institucional do TCC II

Este diretório contém a fonte editável do artigo científico estendido destinado à submissão do TCC II no Oriente. Ele é separado do plano-mestre e segue a [decisão sobre o artigo institucional (DEC-019)](../docs/decision-log.md#dec-019).

## Estado atual

A fonte corrente é **pré-experimental**, revisada em **17/10/2026** conforme o plano **v1.2.19** e o [corte de entrega (DEC-058)](../docs/decision-log.md#dec-058). Ela distingue M1/M2 históricos das provas posteriores de caminhos privados C0/C1, captura/restauração e registro candidato v2. Integração operacional completa, revisão independente, piloto, freeze e coleta principal continuam pendentes; os testes técnicos não fornecem taxas científicas de eficácia.

O compromisso é um único modelo DeepSeek, 90 pares/180 documentos, C0/C1 e três repetições: **1.080 execuções principais**, mais **144 do piloto separado**, totalizando **1.224**, sem retries. Qwen3, ablação e ataques adaptados à defesa são trabalhos futuros, não blocos condicionais desta entrega. H4 deixa de ser hipótese de aceitabilidade e a eficiência será descritiva; RQ4/H5 ficam retiradas com IDs reservados. H1/H3/H2, a margem de −10 pontos percentuais, o pareamento e os gates de poder/intervalos permanecem. A revisão dirigida da literatura não é apresentada como revisão sistemática executada.

O PDF serve para revisão científica, editorial e de template com o grupo e o orientador, não para submissão final. Após qualquer edição de fonte, sua compilação, relatório e inspeção visual precisam ser renovados na mesma árvore; um `PASS` histórico não vale para a nova fonte.

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

A compilação de 17/10/2026 tem **18 páginas**, Resumo de **213 palavras** e Abstract de **189**, com 20 citações e referências reconciliadas. Passou nos gates automáticos, metadados e inspeção das 18 páginas, sem caixas excedentes ou referências indefinidas. Os hashes dos fontes, PDF e log final estão em `validation-report.json`. Isso valida o artefato editorial pré-experimental, não os resultados científicos ou a aprovação humana para envio.

Também é possível compilar com a toolchain TeX Live já instalada no Ubuntu/WSL, sem rede ou instalação de pacotes. A sequência é pdfLaTeX, BibTeX no diretório de saída e mais duas passagens de pdfLaTeX, com fontes e estilos resolvidos localmente. Usar `-no-shell-escape`, manter auxiliares em `.runtime` e registrar versões e hashes. Se faltar dependência, interromper e relatar; não ativar instalação automática durante a compilação.

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
