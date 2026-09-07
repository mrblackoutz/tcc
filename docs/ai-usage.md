# Registro de uso de ferramentas de IA

**Exigido por:** §23 do plano-mestre. **Tarefa:** ADM-11. **Decisão:** DEC-022 (achado IA-01).

Este registro existe independentemente da política institucional de IA, que ainda não foi
recuperada (ADM-02). Registro de uso é evidência contemporânea: reconstruí-lo em novembro
para trabalho feito entre agosto e outubro seria, na melhor hipótese, impreciso. Quando a
política institucional for obtida, a declaração exigida será **derivada** deste arquivo, e
não redigida de memória.

## Regras

1. Toda ferramenta de IA usada em pesquisa, engenharia, redação ou revisão entra na tabela,
   com período, etapa, tipo de contribuição, revisor humano e verificação aplicada.
2. Nenhuma fonte, número ou resultado experimental pode ser gerado por IA sem verificação
   humana na fonte original. Referência bibliográfica exige conferência no veículo.
3. Nenhuma execução científica pode ser produzida ou interpretada por ferramenta que não
   esteja declarada no manifesto do congelamento.
4. Linhas reconstituídas a partir do histórico Git são marcadas como tal. Não se apresenta
   como contemporâneo o que não é.
5. O arquivo é atualizado a cada release do plano e a cada seção do artigo.

## Registro

| Período | Ferramenta/modelo | Etapa | Contribuição | Revisor humano | Verificação aplicada |
|---|---|---|---|---|---|
| 25/08–01/09/2026 | assistente de código baseado em LLM | engenharia e redação | apoio na redação do plano-mestre, dos scripts de laboratório e da documentação técnica das versões 1.0 a 1.2.10 | Gustavo (P3) | *reconstituído a partir do histórico Git*; granularidade por commit, não por sessão. Cada aceite técnico (M1, M2, G3a, G3b, G3c) foi validado por execução e hash registrados nos locks |
| 05/09/2026 | assistente de código baseado em LLM (Claude Opus) | revisão e engenharia | revisão adversarial do plano em doze dimensões (`docs/revisao-independente-v1.2.9.md`); correção do executor C0; correções de reprodutibilidade do smoke; implementação do `T-A2-PREFREEZE` | Gustavo (P3) | referências verificadas contra ACL Anthology, PMLR, USENIX e registros DOI; 100 testes executados em contêiner; smoke M1/M2 executado contra Odoo real com hashes de estado conferidos; resultado do `T-A2-PREFREEZE` observado em execução, não inferido |

## Pendências

- ADM-02: confirmar no Oriente a política institucional de uso e declaração de IA e derivar
  daqui a declaração exigida.
- Manter o registro por sessão, e não por commit, a partir de 05/09/2026.
