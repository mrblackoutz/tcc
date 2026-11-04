# Checklist de submissão — artigo TCC II

**Estado:** versão de trabalho de **31/10/2026**, revisada a partir da [auditoria documental do Felipe](../docs/reviews/2026-10-29-auditoria-felipe.md). Propostas e resultados do estado Odoo são reportados separadamente, com 144 ciclos tecnicamente válidos. Compilação offline, validação automática e inspeção visual das páginas alteradas renovadas; hashes e histórico no `validation-report.json`. Não há congelamento formal nem aceite humano inventado. O envio depende dos itens institucionais abertos.

## Estrutura e formato

- [x] PDF corrente possui entre 10 e 20 páginas, incluindo referências: 19
- [x] Resumo corrente possui entre 150 e 250 palavras: 244 (regra de contagem no README)
- [x] Abstract corrente possui entre 150 e 250 palavras e é semanticamente equivalente ao Resumo: 234
- [x] Palavras-chave e Keywords foram conferidos no PDF corrente
- [x] seis títulos principais aparecem literalmente na ordem exigida no PDF corrente
- [ ] referências correntes seguem estilo autor-data compatível com ABNT NBR 6023:2018 — siglas protegidas e metadados conferidos em 31/10 (Crossref, ACL Anthology, USENIX, NeurIPS); falta confirmar a versão da ABNT aceita pela FCI
- [x] toda citação corrente possui referência e toda referência é citada: 20/20
- [ ] PDF corrente foi comparado visualmente com o template FCI 2026 — posição do orientador confere; segunda afiliação ("se houver") e e-mails do template dependem de decisão do grupo e do orientador
- [ ] caixa de "versão de trabalho" removida só na versão final aprovada (`\workingdraftfalse` em `main.tex`)
- [x] capa, tabelas densas, mudanças de seção e referências correntes foram inspecionadas
- [x] PDF corrente não tem página intermediária formada apenas por cabeçalho ou linha residual de tabela

## Conteúdo científico

- [x] título atual corresponde à orientação e ao escopo vigente
- [x] caso de uso delimitado a Contas a Pagar e Odoo 19.0 Community
- [x] problema, público-alvo, lacuna, RQs, hipóteses e objetivo estão explícitos
- [x] método diferencia C0/C1, unidade, ameaça, dataset, métricas e análise descritiva
- [x] fontes refletem a avaliação de 12 pares/24 documentos, três repetições (144 execuções no Odoo) e três objetivos financeiros, sem exposição de dados
- [x] fontes posicionam o conjunto de 90 pares (1.080 execuções), Qwen3, ablação e ataques adaptados à defesa como trabalhos futuros
- [x] fontes retiram RQ4/H4/H5 como compromissos, preservam IDs (H1–H5, RQ1–RQ4) e reportam segurança e utilidade como taxas e diferenças com IC95% (margem de 10 pontos só como referência)
- [x] fontes declaram as três limitações: amostra pequena, enquadramento escolhido após observar o piloto e revisão de partes feita apenas por IA
- [x] perguntas e hipóteses possuem definição e links internos conferidos no PDF corrente
- [x] ausência de participantes humanos está declarada
- [x] M1/M2 e incrementos privados posteriores são relatados como provas técnicas, não eficácia de C1
- [x] numeradores, denominadores e IC95% do Odoo coincidem com as fontes auditadas; sem campos de resultado por preencher
- [x] adapter LLM e propostas de C0/C1 foram medidos nas duas rodadas do piloto
- [x] C1 e seus testes de autorização foram revisados por segundo agente de IA
- [x] revisão dirigida tem matriz crítica e registro verificável de origem/data/seleção; não é apresentada como busca sistemática executada
- [x] ciclo integrado concluído: 144 registros, 576 capturas, 144 restaurações e denominadores reconciliados
- [x] Resultados, Resumo, Abstract e Conclusão preenchidos com ASR-state, UACR, BTSR e IC95% auditados; Introdução/capa alinhadas
- [x] limitações revistas: zero eventos não demonstra redução/equivalência; amostra pequena, enquadramento posterior, sem freeze e revisão por IA

## Privacidade, metadados e segurança

- [x] pacote bruto do TCC I/template não integra o artigo versionado
- [x] e-mails, identificadores acadêmicos, documentos reais e segredos não foram copiados
- [x] metadados incorretos do template não foram herdados
- [ ] afiliações e contatos finais foram conferidos e consentidos — o template mostra e-mails; a regra do repositório proíbe e-mails nas fontes versionadas
- [ ] PDF final foi revalidado por scanner de segurança e inspeção de metadados
- [x] hashes de fontes, PDF e log correspondem à mesma compilação; dados citados rastreados ao lote auditado, sem alegar freeze formal

## Gates do Oriente

- [x] extensão aceita pela tarefa de submissão foi confirmada: PDF (informado por Gustavo em 31/10/2026)
- [x] anexo da declaração de IA não conta nas 20 páginas do artigo (informado por Gustavo em 31/10/2026)
- [x] edital V5, citado na auditoria do Felipe, registrado com arquivo e hash (31/10/2026)
- [ ] política institucional de uso/declaração de IA foi confirmada e atendida — formulário preenchido e depois removido, segundo Felipe; respostas rascunhadas em [respostas da declaração de IA](../docs/declaracao-ia-respostas.md); enviado em 31/10; três alunos assinaram em 01/11; falta a assinatura do orientador e gerar o PDF de submissão com `paper/build_submission.sh`
- [ ] alinhamento do tema à área/projeto do orientador foi confirmado formalmente
- [ ] grupo e orientador aprovaram o conteúdo e a versão final
- [ ] autores e orientador constam corretamente no cadastro do Oriente
- [ ] grupo aprovou a versão interna até 02/11; arquivo foi enviado até 08/11 dentro da janela institucional de 03 a 09/11/2026
- [x] PDF único para assinatura (artigo + declaração sem assinaturas) gerado por `paper/build_submission.sh` em 04/11: 22 páginas (19 + 3), validado com as páginas do anexo fora do limite e mantido fora do Git
- [ ] PDF único assinado pelos três alunos e pelo orientador e aprovado por `paper/check_signed_submission.sh`
- [ ] recibo de submissão foi preservado fora do Git
