# Auditoria documental do Felipe (29/10/2026) e tratamento (31/10/2026)

**Origem:** relatório "Auditoria final do artigo TCC II", 3 páginas, enviado por Felipe a Gustavo. O arquivo fica fora do Git (SHA-256 `6502698eb9b369680eda6fdffec0904d1849918bd15ebc823ddbad8fcbbef642`).

**Versão auditada:** a do commit `1a339d2`, com PDF `bdd362554a03e97bc3eb2c16601bec9231bb4e309592608ebc02b91361a7fe46`. A identificação é inferida dos números que o relatório cita: Resumo de 238 palavras, Abstract de 222, 217.862 tokens e cerca de US$ 0,03.

**Natureza:** revisão humana e documental de um autor. Ela não substitui a revisão independente nem a aprovação do grupo e do orientador.

**Tratamento:** feito por Gustavo com o assistente de código em 31/10/2026, sem nova execução, chamada à API, mudança de dados, números, política ou código do experimento.

## O que a auditoria confirmou

- **Números:** Resumo, Abstract, Conclusão, Tabela 9 e a documentação do piloto concordam:
  - 144 execuções;
  - ataques bem-sucedidos no ERP 0/36 e contabilizações sem autorização 0/12 em cada versão;
  - tarefas normais concluídas 36/36 e 35/36;
  - diferença de −2,8 pontos, com intervalo de [−13,9; 0,0].
- **Limites:** o texto não afirma redução de ataques, equivalência de segurança nem não inferioridade.
- **Configuração:** os sete itens da [conferência pelo grupo](../configuracao-avaliada.md#conferência-pelo-grupo) batem com o artigo. A coluna do Felipe foi marcada.
- **Estrutura:** 19 páginas e 20 citações para 20 referências. A declaração de IA ainda não estava anexada.

## Tratamento de cada apontamento

| # | Prioridade | Apontamento | Tratamento |
|---|---|---|---|
| 1 | Alta | `referencias.bib`: proteger siglas e nomes próprios nos títulos | **Aplicado.** `{StruQ}`, `{AgentDojo}`, `{InjecAgent}`, `{DRIFT}` e `{LLM}` em cinco títulos. Conferido nas p. 18–19 do PDF novo. |
| 2 | Alta | `main.tex`: caixa de "versão de trabalho" e identificação do orientador | **Caixa mantida até a aprovação**, como o próprio item pede. Para removê-la na versão final, basta trocar `\workingdrafttrue` por `\workingdraftfalse`. A data da caixa passou para 31/10. A posição do orientador, numa linha própria abaixo dos alunos, confere com o template. O sobrescrito 2 (programa de pós-graduação, "se houver") e os e-mails que o template mostra dependem de decisão humana: **BLOQUEADO**, sem inventar afiliação ou contato. |
| 3 | Alta | `validation-report.json`: revisão antiga ligada a outro PDF | **Aplicado.** A revisão por agente continua ligada ao PDF `a6631dc8…`. O relatório ganhou o histórico das versões seguintes, esta auditoria como revisão humana da versão `bdd36255…` e o registro de que as mudanças de 31/10 ainda não tiveram revisão independente. Nenhum PASS foi atribuído a quem não revisou. |
| 4 | Alta | Edital V5 em `institutional-requirements.md` e no checklist | **Registrado como informado pelo Felipe.** O arquivo do V5 não está no repositório nem na máquina, então hash e leitura própria ficam **BLOQUEADOS** até recebê-lo. O histórico do V4 foi preservado e nenhum item foi marcado como concluído sem comprovante. |
| 5 | Média | `build.ps1`: `-no-shell-escape` e não substituir o PDF se a validação reprovar | **Aplicado.** `-no-shell-escape` e `--disable-installer` em todas as chamadas do MiKTeX. O PDF temporário é validado antes de substituir o versionado; com `-SkipValidation`, o versionado não é tocado. **Testado em cópia isolada:** com o Resumo inflado para 284 palavras, a compilação saiu com erro e o PDF anterior ficou intacto; na compilação normal, passou e substituiu. **Achado extra:** o `validate_paper.ps1` reprovava qualquer PDF no Windows, porque lia a saída do `pdfinfo` na codificação OEM e o título acentuado não batia. Corrigido. |
| 6 | Média | Critério de contagem de palavras divergente (238/222 contra 229/217) | **Esclarecido.** Os dois validadores usam a mesma regra (descrita no [README do artigo](../../paper/README.md#compilação)). Os números 229/217 eram de 27/10 e não tinham sido atualizados no README e no checklist. Contagem atual nos dois validadores: 244 e 234. |
| 7 | Média | Clareza de "proposta adversarial comprometida", "the sole failure" e "schema" | **Aplicado** no Resumo, no Abstract e na Conclusão. "Em nenhuma execução adversarial o modelo propôs o valor do atacante"; "the only lost benign task"; "formato exigido (schema)". Mesmos números e mesmo sentido nas duas línguas. |
| 8 | Verificar | Metadados das referências e versão da ABNT | **Conferido em 31/10** na Crossref (por DOI), na ACL Anthology, na USENIX e no NeurIPS. Detalhes abaixo. A versão da ABNT aceita pela FCI fica **BLOQUEADA**: o Guia e o Regulamento Geral de TCC não estão disponíveis. |
| 9 | Verificar | Distinguir "ataques estáticos definidos antes da coleta" de "sem congelamento formal" | **Aplicado** nas seções 3.8, 4.5 e 5. A configuração e o conjunto estático de ataques foram registrados antes da coleta. O congelamento formal do protocolo original, com aceite assinado, não ocorreu; por isso os registros mantêm `scientific_run=false`. |

### Conferência das referências

| Referência | Fonte consultada | Resultado |
|---|---|---|
| Greshake 2023, InjecAgent 2024, Task Shield 2025, Yi 2025, Peffers 2007, Wohlin 2012 | Crossref e, para os artigos da ACL, a ACL Anthology | Título, anais, páginas e ano conferem. |
| StruQ 2025 | página oficial da USENIX | Autores e páginas 2383–2400 conferem. |
| AgentDojo 2024 | Crossref e página do NeurIPS | Páginas 82895–82920 nas duas fontes. **Acrescentadas.** |
| Adaptive Attacks 2025 | ACL Anthology e Crossref | A ACL Anthology, fonte oficial, dá 7116–7132, igual ao arquivo; a Crossref traz 7101–7117. **Mantido.** |
| DRIFT 2025 | Crossref e página do NeurIPS | As páginas divergem (Crossref 92825–92853; NeurIPS 83262–83290). **Ficou sem páginas.** O terceiro autor aparece com nome e sobrenome invertidos nas duas fontes; não aparece no PDF, que usa "et al.". |
| Hevner 2004 | Crossref | A Crossref traz 75–106; a citação usual e o arquivo usam 75–105. **Mantido, divergência anotada.** |
| NIST AI 600-1 | Crossref | Título e ano conferem. A Crossref registra a instituição como autora; o arquivo lista os oito autores do documento. |
| Páginas web (OWASP, Odoo, DeepSeek, Qwen) | — | Não reconferidas; o acesso registrado é de 31/08/2026. |

## Checagens executadas em 31/10/2026

- **Compilação:** TeX Live no WSL com `-no-shell-escape`, BibTeX e três passagens adicionais, sem avisos do LaTeX.
- **`scripts/validate_current_docs.py` com o PDF:** PASS. 19 páginas, Resumo com 244 palavras, Abstract com 234, 20 citações para 20 referências, nenhuma caixa excedente e nenhuma referência indefinida.
- **`paper/validate_paper.ps1` no Windows:** PASS.
- **`paper/build.ps1`:** os dois testes em cópia isolada descritos no item 5.
- **Inspeção visual:** páginas 1, 2, 12, 13, 16, 17, 18 e 19 a 80 dpi; as 19 páginas a 60 dpi.
- **PDF novo:** SHA-256 `1d64b019164d865819eb17882fff92ed0b56c9719b521fab31345c81f40b9cf3`.

## O que continua aberto

- **Edital V5:** falta receber o arquivo para registrar o hash e confirmar as p. 7–8 e 17 citadas pelo Felipe.
- **Declaração de IA:** segundo o Felipe, o formulário foi preenchido e depois removido. Falta confirmar se o PDF gerado foi baixado ou chegou por e-mail e colher as quatro assinaturas. Se não houver cópia, pedir pela coordenação. Não presumir que o formulário removido invalide ou comprove o envio.
- **Perguntas ao Oriente ou à coordenação:** qual extensão de arquivo é aceita e se o anexo da declaração conta nas 20 páginas. O artigo tem uma página de folga.
- **Conferência humana:** equivalência visual com o template oficial, afiliações e contatos autorizados, aprovação final do grupo e do orientador.
- **Revisões pendentes:** a coluna do Thomaz na conferência da configuração e a revisão independente da versão final.
