# Artigo institucional do TCC II

Este diretório contém a fonte editável do artigo científico estendido destinado à submissão do TCC II no Oriente. Ele é separado do plano-mestre e segue a [decisão sobre o artigo institucional (DEC-019)](../docs/decision-log.md#dec-019).

## Estado atual

A fonte corrente foi atualizada em **27/10/2026** com os [resultados do piloto no Odoo](../docs/pilot-state-resultado.md), a [DEC-098](../docs/decision-log.md#dec-098) e a [revisão independente](../docs/reviews/2026-10-27-piloto-concluido.md). Em **31/10/2026** recebeu os ajustes da [auditoria documental do Felipe](../docs/reviews/2026-10-29-auditoria-felipe.md). A avaliação descritiva tem **12 pares, 24 documentos e 144 execuções**, com novas chamadas ao `deepseek-flash` dentro de cada slot; as duas rodadas anteriores de propostas são reportadas separadamente. Os ciclos foram tecnicamente válidos, o que não significa conclusão de todas as tarefas.

No ERP, ASR-state foi 0/36 e UACR 0/12 em cada condição; BTSR foi 36/36 em C0 e 35/36 em C1, diferença de −2,8 pontos percentuais e IC95% BCa por par [−13,9; 0,0]. A falha foi saída fora do schema, sem bloqueio da política. Não se demonstra redução de ataques, equivalência de segurança ou não inferioridade. O texto declara amostra pequena, modelo único, enquadramento após o estágio de propostas, ausência de freeze formal e revisão por agentes sem assinatura humana.

Foram corrigidos prompt/envelope comuns, origem das propostas, embaralhamento global, parada conservadora da captura, exceção do provedor e análise sem McNemar. A custódia é uma cópia local DPAPI com restauração verificada, sem imutabilidade ou proteção externa. Os 90 pares adicionais, Qwen3, ablação e ataques adaptados à defesa permanecem como trabalhos futuros. Não há campos de resultado por preencher.

O PDF serve para revisão científica, editorial e de template com o grupo e o orientador. Após qualquer edição de fonte, sua compilação, relatório e inspeção visual precisam ser renovados na mesma árvore; um `PASS` histórico não vale para a nova fonte.

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

Arquivos auxiliares e logs ficam em `.runtime`, fora do Git. O script usa `-no-shell-escape`, impede o MiKTeX de instalar pacotes durante a compilação e valida o PDF novo antes de copiá-lo para este diretório. Se a validação reprovar, o PDF versionado fica como estava. Com `-SkipValidation`, o PDF novo fica só em `.runtime/paper-build`.

A compilação de **31/10/2026**, com TeX Live instalado no Ubuntu/WSL, tem **19 páginas**, Resumo de **244 palavras** e Abstract de **234**. Foram reconciliadas 20 citações e 20 referências; não há placeholders de resultados, caixas excedentes ou referências indefinidas. As 19 páginas foram inspecionadas, incluindo a tabela de resultados em detalhe. Fontes, PDF, log, versões e limites de aceite estão registrados em `validation-report.json`.

Também é possível compilar com a toolchain TeX Live já instalada no Ubuntu/WSL, sem rede ou instalação de pacotes. A sequência é pdfLaTeX, BibTeX no diretório de saída e mais duas passagens de pdfLaTeX, com fontes e estilos resolvidos localmente. Usar `-no-shell-escape`, manter auxiliares em `.runtime` e registrar versões e hashes. Se faltar dependência, interromper e relatar; não ativar instalação automática durante a compilação.

Com Python e Poppler disponíveis no WSL/Linux, a verificação de documentação e artigo pode ser executada a partir da raiz:

```bash
python3 scripts/validate_current_docs.py --paper-pdf paper/relatorio_tcc_ii.pdf --paper-log /caminho/do/build/main.log
```

O log precisa ser da mesma compilação do PDF. A inspeção visual continua obrigatória e é registrada separadamente.

**PDF de submissão:** o edital exige a declaração de uso de IA assinada anexada ao fim do artigo, e a secretaria confirmou que ela não conta nas 20 páginas. No WSL ou Linux, a partir da raiz:

```bash
bash paper/build_submission.sh <declaracao-assinada.pdf>
```

O script compila o artigo sem a caixa de "versão de trabalho", com a declaração depois das referências, e valida o resultado descontando as páginas do anexo. Ele funciona de dois modos, conforme a declaração recebida:

- **Declaração sem assinaturas (caminho adotado):** gera `.runtime/submission/relatorio_tcc_ii_para_assinatura.pdf`, um arquivo único com artigo e declaração, que os três alunos e o orientador assinam pelo gov.br. Assim as assinaturas digitais valem sobre o arquivo inteiro que vai para o Oriente. Depois das assinaturas, rode:

  ```bash
  bash paper/check_signed_submission.sh <arquivo-assinado.pdf>
  ```

  A checagem exige ao menos quatro assinaturas íntegras, o mesmo número de páginas, o mesmo texto nas páginas do artigo e todas as linhas originais da declaração. O arquivo aprovado é copiado para `.runtime/submission/relatorio_tcc_ii_submissao.pdf`.
- **Declaração já assinada (alternativa):** confere as assinaturas com o `pdfsig` e achata o arquivo com o `pdftocairo`, porque os carimbos do gov.br são anotações que o `pdfpages` descartaria. A cópia achatada perde a validação criptográfica, que fica só no original assinado.

Nada disso vai para `paper/` nem para o Git, porque a declaração traz RAs e um e-mail.

**Contagem de palavras:** `validate_paper.ps1` e `scripts/validate_current_docs.py` contam a partir da fonte do Resumo e do Abstract, com a mesma regra:

- retiram comentários, comandos LaTeX, chaves, `~` e travessões;
- contam sequências de letras e números;
- hífen ou apóstrofo interno não divide a palavra: `deepseek-flash` e `C0's` contam uma vez;
- números separados contam separadamente: `0/36` são duas palavras.

As duas contagens devem coincidir; o valor registrado é o do `validation-report.json` da compilação corrente.

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

Os resultados do Odoo e os intervalos auditados estão preenchidos. Antes do envio, falta atender aos gates institucionais: extensão aceita, declaração de IA assinada, contatos, aprovação final do grupo/orientador e comparação com o arquivo de template vigente. Consulte `SUBMISSION_CHECKLIST.md`.
