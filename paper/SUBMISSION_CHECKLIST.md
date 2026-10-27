# Checklist de submissão — artigo TCC II

**Estado:** versão de trabalho de 26/10/2026, plano v1.2.19 e [corte da entrega (DEC-058)](../docs/decision-log.md#dec-058), com o estágio de propostas do piloto reportado. Compilação, validação automática e inspeção das 19 páginas renovadas na mesma árvore; hashes no `validation-report.json`. O checklist diferencia PDF tecnicamente válido, revisão humana e autorização de envio; a submissão continua bloqueada pelos itens abertos abaixo.

## Estrutura e formato

- [x] PDF corrente possui entre 10 e 20 páginas, incluindo referências: 19
- [x] Resumo corrente possui entre 150 e 250 palavras: 242
- [x] Abstract corrente possui entre 150 e 250 palavras e é semanticamente equivalente ao Resumo: 217
- [x] Palavras-chave e Keywords foram conferidos no PDF corrente
- [x] seis títulos principais aparecem literalmente na ordem exigida no PDF corrente
- [ ] referências correntes seguem estilo autor-data compatível com ABNT NBR 6023:2018
- [x] toda citação corrente possui referência e toda referência é citada: 20/20
- [ ] PDF corrente foi comparado visualmente com o template FCI 2026
- [x] capa, tabelas densas, mudanças de seção e referências correntes foram inspecionadas
- [x] PDF corrente não tem página intermediária formada apenas por cabeçalho ou linha residual de tabela

## Conteúdo científico

- [x] título atual corresponde à orientação e ao escopo vigente
- [x] caso de uso delimitado a Contas a Pagar e Odoo 19.0 Community
- [x] problema, público-alvo, lacuna, RQs, hipóteses e objetivo estão explícitos
- [x] método diferencia C0/C1, unidade, ameaça, dataset, métricas, freeze e análise
- [x] fontes mantêm 90 pares/180 documentos, três repetições e três objetivos financeiros, sem exposição de dados
- [x] fontes preservam 1.080 execuções principais e 144 piloto; Qwen3, ablação e ataques adaptados à defesa são trabalhos futuros
- [x] fontes retiram RQ4/H4/H5 como compromissos, preservam IDs e tratam eficiência e subgrupos como descrição
- [x] fontes preservam H1 → H3 → H2, margem −0,10, dependência das repetições e gates de poder/intervalos
- [ ] perguntas e hipóteses possuem definição e links internos conferidos no PDF corrente
- [x] ausência de participantes humanos está declarada
- [x] M1/M2 e incrementos privados posteriores são relatados como provas técnicas, não eficácia de C1
- [x] não há percentuais confirmatórios inventados
- [ ] adapter LLM e C0 científico competente foram validados no piloto
- [ ] C1 e seus testes de autorização foram concluídos
- [ ] revisão dirigida tem matriz crítica e registro verificável de origem/data/seleção; não é apresentada como busca sistemática executada
- [ ] transporte, supervisão, autorização, captura, registro e reset estão integrados e revisados; `execute` não é aberto por este corte
- [ ] dataset final e ground truth foram revisados, hasheados e congelados
- [ ] experimento principal foi executado e todos os denominadores foram reconciliados
- [ ] Resultados, Resumo, Abstract e Conclusão foram atualizados com efeitos e IC95% reais
- [ ] ameaças à validade foram revistas à luz dos dados observados

## Privacidade, metadados e segurança

- [x] pacote bruto do TCC I/template não integra o artigo versionado
- [x] e-mails, identificadores acadêmicos, documentos reais e segredos não foram copiados
- [x] metadados incorretos do template não foram herdados
- [ ] afiliações e contatos finais foram conferidos e consentidos
- [ ] PDF final foi revalidado por scanner de segurança e inspeção de metadados
- [ ] fonte, PDF, referências e dados citados correspondem ao mesmo commit/freeze

## Gates do Oriente

- [ ] extensão aceita pela tarefa de submissão foi confirmada
- [ ] política institucional de uso/declaração de IA foi confirmada e atendida
- [ ] alinhamento do tema à área/projeto do orientador foi confirmado formalmente
- [ ] grupo e orientador aprovaram o conteúdo e a versão final
- [ ] autores e orientador constam corretamente no cadastro do Oriente
- [ ] grupo aprovou a versão interna até 02/11; arquivo foi enviado até 08/11 dentro da janela institucional de 03 a 09/11/2026
- [ ] recibo de submissão foi preservado fora do Git
