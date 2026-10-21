# Backlog operacional completo do TCC II

**Decisão de ownership:** [divisão do trabalho (DEC-021)](decision-log.md#dec-021)

**Data-base:** 21/10/2026

**Estado científico:** pré-congelamento. O [corte aprovado (DEC-058)](decision-log.md#dec-058) concentra a entrega em **DeepSeek, C0/C1, 90 pares e três repetições: 1.080 execuções principais + 144 do piloto separado = 1.224**. Qwen3, ablação e ataques adaptados à defesa passam a trabalho futuro; suas tarefas são `CUT`, não concluídas. A [captura/reset e oráculo (DEC-055)](lab-runbook.md#captura-restauracao-oraculo) e o [registro candidato v2 (DEC-057)](lab-runbook.md#run-record-candidato) já têm evidência técnica; não reconstruí-los. **Próximo: integrar o ciclo operacional mínimo, produzir/revisar o piloto, validar a análise com dados sintéticos e escrever o artigo em paralelo.** RUN-01/02/03/04/08 seguem `ACTIVE`; `execute` fechado. SCI-01 foi reaberta pelo escopo revisto; SCI-03, imagem experimental, revisão humana, competência C0, dataset e freeze continuam gates. Não expandir engenharia auxiliar sem necessidade demonstrada para esse fluxo.

**Por que os 144 runs do piloto ainda não começaram?** Testes de componentes não substituem o ciclo experimental. Restam três frentes:

- **Fixtures completas — DATA-06/05:** existem 12 bases, quatro origens benignas A3a e [cinco bancos alternativos](lab-runbook.md#cadastros-alternativos-piloto). A [relação pedido/produto A1 foi corrigida e conferida na candidata `.3` (DEC-071)](lab-runbook.md#correcao-pedido-produto), sem mudar resolvedor ou defesa. Restam aprovação/materialização dos outros membros e entrega verificada ao modelo.
- **Ciclo único — C0-01/03 e RUN-02/04/09:** o [handoff observado REVIEW→fixture→POST (DEC-069)](lab-runbook.md#handoff-post-observado) passou em desenvolvimento, mas falta ligar dados revisados, entrada comum/LLM real, C0/C1, oráculo, registros, supervisão e restauração por execução num ensaio conjunto. Não reconstruir os componentes existentes.
- **Aceite independente — DATA-04, C0-05, C1 e SCI-03:** revisar os 24 documentos e os controles/protocolo pendentes; fechar configuração operacional e custódia/orçamento para o lote. Assistência automatizada e testes não assinam revisão humana.

O **freeze final é posterior ao piloto**, não uma pré-condição deste. Competência C0 também será medida no piloto. A saída imediata é concluir essas três frentes e executar PILOT-01/02, sem abrir o conjunto final ou ampliar engenharia auxiliar.

**Leitura dos códigos:** [C0](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#c0) é a integração direta; [C1](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#c1), a integração protegida. RQ significa pergunta de pesquisa; H, hipótese; DEC, decisão registrada. Os links levam ao significado completo. Consulte a [leitura rápida](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#leitura-rapida) antes de iniciar uma tarefa.

## 1. Como usar este backlog

Este arquivo é a fila única de trabalho restante. Uma tarefa só muda para `DONE` quando o entregável e a Definition of Done (DoD) indicados existem e foram revisados. Percentual subjetivo, código sem teste, texto sem fonte ou execução sem manifest não concluem tarefa.

Estados permitidos:

- `READY`: pode começar sem aguardar outra tarefa;
- `ACTIVE`: possui owner trabalhando e próximo checkpoint definido;
- `AWAITING_REVIEW`: artefato, testes, documentação e evidência técnica não dependente de revisão estão completos e commitados; falta somente revisão/assinatura independente. Permite iniciar dependentes de engenharia sobre contrato versionado, mas **não** satisfaz gates de piloto, freeze ou resultado científico; ver [regra de aceite intermediário (DEC-034)](decision-log.md#dec-034);
- `WAIT`: depende de outro ID interno;
- `EXTERNAL`: depende de orientador, Oriente, credencial ou autorização do operador;
- `CONDITIONAL`: só entra se o núcleo estiver protegido em prazo/recursos;
- `DONE`: evidência aceita e commitada;
- `CUT`: retirada conscientemente da entrega por decisão registrada; não equivale a implementada, testada ou `DONE`. ID, ownership e evidência histórica permanecem.

Prioridades:

- `P0`: prazo institucional ou caminho crítico do experimento;
- `P1`: obrigatório para excelência/reprodutibilidade, mas não bloqueia a tarefa desta semana;
- `P2`: estudo secundário condicionado;
- `P3`: opcional e cortado antes de qualquer item do núcleo.

## 2. Papéis e fronteiras de ownership

| Papel | Integrante | Ownership primário | Revisor padrão |
|---|---|---|---|
| P1 — ciência e dados | Felipe Ujvari Gasparino de Sousa | protocolo, literatura, dataset, ground truth, estatística, análise e coerência do artigo | P3 para fatos/execução; P2 para segurança |
| P2 — arquitetura e segurança | Thomaz de Souza Scopel | C0 plausível, C1, policy engine, approval, capabilities, add-on, ACLs e testes adversariais | P3 para Odoo; P1 para aderência ao protocolo |
| P3 — Odoo e experimentação | Gustavo Nascimento Siqueira | ambiente, egress/runtime LLM, Odoo, fixtures, runner, oráculo, reset, manifests e reprodução | P2 para segurança; P1 para dados/métricas |

Ownership não significa trabalho isolado. Owner implementa e responde pelo DoD; reviewer tenta invalidar a evidência. Mudança em contrato compartilhado exige decisão registrada e revisão dos dois consumidores.

### 2.1 Arquivos preferencialmente exclusivos

| Trilha | Caminhos de trabalho | Regra de integração |
|---|---|---|
| P1 | `docs/protocol.md`, `docs/literature-review.md`, `dataset/`, `analysis/`, seções científicas do artigo | não altera schema/runtime sem revisão P2/P3 |
| P2 | módulos futuros `policy`, `approval`, `audit`, `capabilities`; `odoo/addons/ap_security_executor`; testes de segurança | não abre conjunto final; usa schemas e exemplos não finais |
| P3 | `compose.yaml`, futuro `infra/llm-client`, `runner/`, scripts, fixtures e oráculo Odoo | não muda hipótese/métrica; publica contratos antes de integrar |
| Compartilhado | plano, decision/deviation log, locks, manifests de freeze e release | uma única integração por checkpoint; paths explícitos no staging |

<a id="3-caminho-crítico-e-ondas-paralelas"></a>

## 3. Caminho crítico e cronograma reancorado

```text
protocolo + dados + análise sintética + artigo ─────┐
C0/C1 + revisão dos controles existentes ──────────┼→ piloto → freeze → 1.080 runs → análise final
LLM v2 → despacho → estado/oráculo/registro/reset ─┘                              → artigo final
```

As janelas abaixo são **alvos condicionados à prontidão**, não provas de cumprimento. Substituem as ondas antigas de agosto/setembro, cujo histórico permanece no Git. Se um gate falhar ou a vazão real inviabilizar a janela, registrar o atraso e obter nova decisão; não reduzir pares/repetições, relaxar C1 ou abrir o conjunto final automaticamente.

| Onda | Janela-alvo em 2026 | P1 — Felipe | P2 — Thomaz | P3 — Gustavo | Saída de sincronização |
|---|---|---|---|---|---|
| W0 | 17–20/10 | protocolo reduzido, piloto revisado, análise sintética e literatura/artigo | revisão do C0/C1 existente e despacho mínimo seguro | ciclo operacional, supervisão, registros, reset e vazão | checklist de prontidão real; sem conjunto final |
| W1 | 21–22/10 | QA e relatório do piloto, precisão/poder e dataset final revisado | corrigir achados pré-declarados; assinar segurança | 144 runs do piloto e correções com evidência; preparar freeze | piloto aceito e freeze assinado antes da coleta |
| W2 | 23–26/10 | QA de denominadores sem tuning; artigo em paralelo | acompanhar falhas sem ajustar defesa ao resultado | 1.080 runs intercaladas e custódia dos brutos | coleta íntegra ou suspensão documentada |
| W3 | até 28/10 | análise, figuras, negativos e limites | análise de falhas/mecanismos | conferir manifests, custos e reprodução | tabelas regeneráveis e conclusões proporcionais |
| W4 | até 01/11 | consolidar artigo e referências | revisar arquitetura e claims | conferir método, ambiente e pacote | artigo completo para revisão |
| W5 | 02/11 | revisão científica/editorial | revisão de segurança | revisão de reprodução e build | aprovação interna, condicionada aos gates |
| W6 | até 08/11 | resolver revisão e conferir arquivo | conferir claims finais | submissão e recibo institucional | submissão aceita, sem presumir prorrogação |
| W7 | 10/11–07/12 | slides, respostas, correções e versão final | demo/arguição de segurança | demo/arguição de ambiente | banca, correção e anuência final |

Qwen3, ablação e conjunto defense-aware **não entram nesta entrega**, mesmo que haja folga; sua reativação exige nova decisão. H4 não impõe limites confirmatórios de custo; H5 e RQ4 permanecem retiradas, com IDs reservados. A análise preserva pareamento, três repetições dependentes, bootstrap por par, não inferioridade de `−0,10`, missing e a validação dos intervalos em zero/fronteira antes do freeze.

## 4. O que fazer agora — três trilhas paralelas

Usar os IDs abaixo como próxima fila, não como nova lista duplicada. Os detalhes, estados e evidências continuam nas tabelas seguintes. As trilhas trabalham independentemente sobre contratos versionados; integração e revisão cruzada fecham o checkpoint. Escrever método/referencial agora, marcando resultados ainda pendentes.

| Integrante | Tarefas iniciais | Não tocar ainda | Checkpoint |
|---|---|---|---|
| Felipe — dados, análise e artigo | SCI-01/03/05–07, DATA-01–04, STAT-01, rascunhos PAPER-01/02 | usar conjunto final para tuning; tratar buscas/matriz como concluídas; prometer H4/RQ4/H5 | schema/codebook, 12 pares piloto com revisão de cada item, análise sintética e texto com fontes |
| Thomaz — C0/C1 mínimo e revisão de segurança | C0-01–03, revisão C1-01–11, SEC-01/02 e SEC-A2 | novo controle auxiliar; conjunto final; gateway com permissão financeira ampla | despacho CREATE/POST restrito e revisado, contabilização benigna autorizada, negativas e invariantes |
| Gustavo — ciclo experimental e integração | G3-06, RUN-01–09, DATA-05/06, ADM-06/09 em apoio ao owner | repetir provas concluídas sem mudança; API sem autorização; Qwen; expansão não necessária | proposta v2 → C0/C1 → estado → oráculo → registro → reset, supervisão e vazão medidas |

**Prontidão até 20/10:** contratos e piloto revisados; fluxo completo ensaiado sem conjunto final; decisão dos retries de observação em SCI-03; análise validada nos casos de fronteira; segurança/custódia e orçamento conferidos. Pendência institucional externa deve ser escalonada imediatamente, sem aguardar a implementação. Não interpretar este alvo como autorização para antecipar piloto ou freeze sem assinatura.

## 5. Administração e requisitos institucionais

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| ADM-01 | P0 | Felipe | Gustavo | — | obter Regulamento Geral e Guia Geral vigentes; registrar origem/hash sem PII | READY |
| ADM-02 | P0 | Felipe | Thomaz | — | confirmar no Oriente extensão de arquivo, política/declaracão de IA e preservar resposta saneada | EXTERNAL |
| ADM-03 | P0 | Felipe | Gustavo | — | confirmar janela/horários/eligibilidade PPI/PPP/PPA e anomalia `31/11`; atualizar matriz | EXTERNAL |
| ADM-04 | P0 | Felipe | Gustavo | — | confirmar dados institucionais e alinhamento do tema à área/projeto do orientador | EXTERNAL |
| ADM-05 | P0 | Felipe | Thomaz | — | instituir registro semanal/quinzenal de orientação com pauta, presença, decisões e próximos passos | READY |
| ADM-06 | P0 | Felipe | Gustavo | — | coletar anuência do orientador no Oriente e preservar recibo fora do Git. Prazo oficial 01/09, vencido; requerimento 565711 em análise pelo orientador desde 01/09. **Escalonamento imediato**: consta no checkpoint seguinte até ser deferida | EXTERNAL |
| ADM-07 | P0 | Gustavo | Felipe | — | cadastro do projeto e três autores confirmados; evidência privada de 01/09 preservada por hash no lock institucional, sem identificadores no Git | DONE |
| ADM-08 | P0 | Gustavo | Felipe | ADM-07 | requerimento protocolado em 01/09, três autores conferidos e evidência privada preservada por hash no lock institucional | DONE |
| ADM-09 | P1 | Gustavo | Felipe | ADM-02 | manter calendário de submissão, avaliadores, banca, correção e anuência final | READY |
| ADM-10 | P0 | Felipe | Thomaz | [divisão do trabalho (DEC-021)](decision-log.md#dec-021) | atualizar requisitos institucionais com papéis nominais; disponibilidade revista semanalmente | DONE |
| ADM-11 | P0 | Felipe | Thomaz | — | manter `docs/ai-usage.md` atualizado a cada release do plano e a cada seção do artigo; derivar dele a declaração institucional quando ADM-02 responder, sem reconstruir de memória | ACTIVE |
| REP-05 | P1 | Gustavo | Thomaz | FRZ-08 | reexecutar a suíte de segurança de C1 em ambiente limpo e registrar tentativa independente de bypass, fechando o ciclo de reprodução dos três componentes | WAIT |
| LIC-01 | P1 | Felipe | Thomaz | ADM-12 | criar `docs/licensing.md` fixando LGPL-3.0-or-later para o add-on derivado do Odoo, licença aberta para gateway/runner/análise e licença própria para o dataset, com compatibilidade verificada contra `gateway/constraints.txt` | READY |
| ADM-12 | P1 | Felipe | Thomaz | — | escolher e adicionar `LICENSE` para código, dataset e documentação, com compatibilidade verificada contra a LGPLv3 do Odoo e as licenças das dependências; registrar a justificativa no decision log | READY |
| ADM-13 | P1 | Felipe | Gustavo | ADM-12 | criar `CITATION.cff` e a seção de instruções de citação no README; conferir contra o checklist de §17.3 do plano | READY |
| SEC-A2 | P0 | Thomaz | Gustavo | — | implementar no executor e no runner a assertion que impede escrita de `partner_id` depois de `partner_bank_id`, conforme o invariante de §16.8 e o resultado do `T-A2-PREFREEZE` | READY |

## 6. Protocolo científico e literatura

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| SCI-01 | P0 | Felipe | Thomaz | — | candidato histórico [DEC-032](decision-log.md#dec-032), commit `d0f11d6`, preservado. Revisar o [protocolo reduzido (DEC-058)](protocol.md): H1→H3→H2, eficiência descritiva, três repetições, zero/fronteira e limitações. Reaberta por mudança de escopo; nova revisão independente/assinatura antes do piloto/freeze | ACTIVE |
| SCI-02 | P0 | Felipe | Gustavo | — | justificar operacionalmente a margem BTSR de 10 p.p. sem usar piloto/final | READY |
| SCI-03 | P0 | Felipe | Thomaz | — | [regras candidatas e classificador puro (DEC-032)](decision-log.md#dec-032) testados offline; faltam parâmetros de retry da observação Odoo, integração, revisão independente e assinatura antes do freeze | ACTIVE |
| SCI-04 | — | Felipe | Gustavo | — | hipótese de aceitabilidade H4 retirada pela [DEC-058](decision-log.md#dec-058), ID reservado. Medição descritiva permanece em RUN-07/AN-05; não escolher limites confirmatórios | CUT |
| SCI-05 | P0 | Felipe | Thomaz | — | revisar procedimento de literatura dirigida: fontes primárias, registro real de consultas/origem/data e critérios de seleção, sem prometer cobertura sistemática ou buscas já concluídas | READY |
| SCI-06 | P0 | Felipe | Thomaz | SCI-05 | executar verificação primária dirigida e matriz crítica de threat model, ambiente, defesa, métricas, resultados/limites e reprodução; conferir contraexemplos à lacuna | WAIT |
| SCI-07 | P0 | Felipe | Thomaz | SCI-06 | congelar formulação da lacuna e claims de originalidade com fontes que sustentem cada frase | WAIT |
| SCI-08 | P1 | Felipe | Gustavo | SCI-03 | registrar ética, ausência de participantes, custódia raw, retenção e revisão dupla de exports | READY |
| SCI-09 | P1 | Felipe | Thomaz | SCI-01 | mapear RQ→hipótese→endpoint→métrica→teste→figura/tabela | WAIT |
| SCI-10 | P1 | Felipe | Gustavo | SCI-05 | reconciliar bibliografia do artigo; remover fonte não citada/não verificável | WAIT |

## 7. G3, egress e baseline C0

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| G3-01 | P0 | Gustavo | Thomaz | [isolamento da chamada ao modelo (DEC-020)](decision-log.md#dec-020), G3a | criar processo/serviço `llm-client` sem credencial Odoo e API interna tipada | DONE |
| G3-02 | P0 | Gustavo | Thomaz | G3-01 | materializar redes separadas e proxy TLS pass-through com allowlist `api.deepseek.com:443` | DONE |
| G3-03 | P0 | Gustavo | Thomaz | G3-02 | testes negativos: gateway/Odoo/db sem Internet; cliente sem ERP/Internet direta; proxy nega host/IP/porta alternativos | DONE |
| G3-04 | P0 | Gustavo | Felipe | G3-01 | harness de smoke sintético, manifest saneado e varredura de logs, ainda com transporte mock | DONE |
| G3-05 | P0 | Gustavo | Thomaz | G3-03, G3-04, autorização | smoke sintético aceito em 24/09: uma chamada sem retry, `deepseek-v4-flash` solicitado e `deepseek-flash` retornado, manifesto saneado e varredura de logs aprovados; [DEC-024](decision-log.md#dec-024) registra o novo roteamento. O prazo de resposta e escalonamento anteriores foram superados pelo aceite | DONE |
| G3-06 | P1 | Gustavo | Felipe | G3-05 | [configuração ratificada (DEC-029)](decision-log.md#dec-029) e [smoke canônico (DEC-030)](decision-log.md#dec-030) aprovados em 26/09: uma inferência sintética com `deepseek-flash`, zero retries e manifesto saneado. O [estágio técnico pré-freeze (DEC-031)](decision-log.md#dec-031) implementa orçamento, espera máxima e retry comum C0/C1 apenas com mocks; faltam supervisão do processo remoto, revisão independente, competência C0 e freeze | ACTIVE |
| G3-07 | — | Gustavo | Thomaz | — | download/proveniência Qwen3 retirados da entrega pela [DEC-058](decision-log.md#dec-058); seleção histórica preservada como trabalho futuro | CUT |
| G3-08 | — | Gustavo | Felipe | G3-07 | benchmark Qwen3 retirado da entrega pela [DEC-058](decision-log.md#dec-058); não afirmar viabilidade ou smoke concluído | CUT |
| A3A-01 | P0 | Gustavo | Thomaz e Felipe | [contrato de ação v2 (DEC-035)](decision-log.md#dec-035) | schemas, adapters e [transporte/consumidores v2 (DEC-050)](decision-log.md#dec-050) preservados. [Prova nativa (DEC-051)](decision-log.md#dec-051) confirma POST C0 sem aprovação no alvo confiável, sem reescrever campos propostos. Faltam revisão independente e aceite da semântica A3a; não é taxa de ataques | AWAITING_REVIEW |
| C0-01 | P0 | Thomaz | Felipe | SCI-01, G3a | especificar prompt-base, ações e ferramentas plausíveis comuns; separar construção C0/C1 do transporte | READY |
| C0-02 | P0 | Thomaz | Gustavo | C0-01, A3A-01 | consumidor v2, ponte e [sete casos nativos (DEC-051)](decision-log.md#dec-051) passaram com identidade funcional não administrativa: CREATE benigno/desvio de valor/beneficiário, POST sem aprovação, alvo ausente/ambíguo e erro nativo. Argumentos, alvo e efeitos conferidos pós-commit. Ainda faltam integração experimental completa, revisão e competência benigna no piloto | ACTIVE |
| C0-03 | P0 | Thomaz | Gustavo | C0-01 | definir capacidades mínimas: rascunho e contabilização autorizada; não ampliar para solicitação simulada de pagamento nesta entrega, sem pagamento/e-mail real | READY |
| C0-04 | P0 | Thomaz | Felipe | C0-02, DATA-05, G3-05, PILOT-02 | medir competência benigna durante o piloto e aceitar o resultado antes do freeze; corrigir apenas falhas funcionais pré-freeze | WAIT |
| C0-05 | P0 | Felipe | Gustavo | C0-02, C0-03 | revisão independente de plausibilidade antes do piloto; documentar diferenças não relacionadas à segurança. Não substitui competência medida em C0-04 | WAIT |

## 8. Dataset, ground truth e red team

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| DATA-01 | P0 | Felipe | Gustavo | contrato atual | [contrato candidato dos pares (DEC-061)](lab-runbook.md#contrato-pares-oraculo): schema/parser fechados, fatos compartilhados, deltas/hashes e ponte tipada para o oráculo sem aprovação/condição. A DEC-064 liga PDFs/textos e verifica unicidade do piloto. Faltam revisão independente, bindings ERP observados, consolidação e futura conferência de separação do conjunto final | ACTIVE |
| DATA-02 | P0 | Felipe | Thomaz | threat model | [codebook candidato v0.1](../dataset/codebook.md) reconciliado com DEC-063 e revisão técnica de templates/A3a sob DEC-064. Faltam aceitação científica independente e integração do benigno autorizado, sem token compartilhado entre proveniências; não revelar conjunto final a P2 | ACTIVE |
| DATA-03 | P0 | Felipe | Thomaz | DATA-01 | [gerador candidato (DEC-062)](lab-runbook.md#geracao-pdfs-desenvolvimento), implementado por Gustavo em contingência: T1/T2/T3, marca por página, extração/hashes e gravação/releitura exclusiva em `.runtime`; somente desenvolvimento. 4.091 testes e dez páginas inspecionadas; faltam revisão técnica de Thomaz e adequação documental por Felipe, sem autorrevisão. Não equivale a dataset revisado | AWAITING_REVIEW |
| DATA-04 | P0 | Felipe | Thomaz | DATA-01–03 | [Coorte candidata local](lab-runbook.md#preparacao-12-pares-piloto), preparada por Gustavo em contingência: 12 pares/24 PDFs, quatro por família, ground truth preliminar e guia dos 24 membros. [Candidata `.3` (DEC-071)](lab-runbook.md#correcao-pedido-produto): um item comercial corrigido nos dois membros A1; 22 PDFs e todas as notas idênticos à `.2`, preservada. Gates humanos/execução falsos; revisão de Felipe e Thomaz pendente, fixtures/Delivery em DATA-06/05. Não é piloto executado nem dataset publicável | AWAITING_REVIEW |
| DATA-05 | P0 | Gustavo | Felipe | DATA-04, G3-04 | validar Delivery Rate: payload chega intacto ao modelo; registrar texto/hash/posição | WAIT |
| DATA-06 | P0 | Gustavo | Felipe | DATA-04 | [Leitor do oráculo](lab-runbook.md#conferencia-fixture-oraculo)/[prova de dois casos](lab-runbook.md#prova-nativa-fixture-oraculo), [12 bases](lab-runbook.md#bases-comerciais-piloto) e [quatro origens benignas A3a](lab-runbook.md#origens-a3a-piloto) preservados. [Cinco bancos e relação pedido/item corrigida (DEC-071)](lab-runbook.md#correcao-pedido-produto) passaram na candidata `.3`: zero lacunas, quatro origens e 12 negativas de vínculo. Restam aprovação legítima exata, materialização/reset dos outros membros e revisão independente. Não são 12 fixtures completas nem piloto executado | ACTIVE |
| DATA-07 | P0 | Felipe | Gustavo | PILOT-04 | gerar/fechar 90 pares/180 documentos finais, 30 pares por objetivo financeiro sem reutilizar itens do piloto | WAIT |
| DATA-08 | P0 | Felipe | Gustavo | DATA-07 | dupla revisão, resolução de divergências, versão/hash/manifest e separação do conjunto final | WAIT |
| DATA-09 | — | Gustavo | Felipe | — | conjunto defense-aware retirado da entrega pela [DEC-058](decision-log.md#dec-058); ID e ownership preservados como trabalho futuro | CUT |
| DATA-10 | P1 | Gustavo | Felipe | DATA-08 | custódia externa criptografada, cópia imutável, retenção e manifest SHA-256 saneado | WAIT |

## 9. Arquitetura C1 e testes de segurança

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| C1-01 | P0 | Thomaz | Felipe | SCI-01, A3A-01 | [tipos e vínculos](../gateway/src/tcc_gateway/policy_contracts.py), [schemas](../gateway/src/tcc_gateway/schemas/policy_contracts_v1.schema.json), catálogo de reason codes e [vetor de hash](../gateway/tests/fixtures/canonical_action_v1.vector.json) commitados em `ba38573`, sob [contratos fechados (DEC-036)](decision-log.md#dec-036); 269 testes offline (62 novos), documentação e segurança aprovados em 30/09. Falta revisão independente de Felipe e conferência de Thomaz; política, verificador de aprovação e execução Odoo pertencem às tarefas seguintes | AWAITING_REVIEW |
| C1-02 | P0 | Thomaz | Felipe | C1-01 | [política determinística](../gateway/src/tcc_gateway/policy_engine.py) e [regressões](../gateway/tests/test_policy_engine.py) commitadas em `79d36be`, sob [avaliação de regras (DEC-037)](decision-log.md#dec-037); 351 testes offline (82 novos), documentação e segurança aprovados em 30/09. Falta revisão independente de Felipe e conferência de Thomaz. Leitura Odoo, token e transação pertencem a C1-03/06/07; dependentes usam o contrato provisoriamente até o aceite | AWAITING_REVIEW |
| C1-03 | P0 | Thomaz | Felipe | C1-01 | [canonicalização/leitor confiável](../gateway/src/tcc_gateway/trusted_resolution.py) e regressões commitados em `4758d41`, sob [leitura independente da proposta (DEC-038)](decision-log.md#dec-038); 533 testes offline (182 novos), 17 Markdown e segurança aprovados em 30/09. Falta revisão humana independente de Felipe e conferência de Thomaz. Prova inclui JSON-2 com HTTP simulado, não integração real/ACLs; ledger, observações operacionais efetivas e revalidação transacional pertencem a C1-06/09 e ao runner; [reprodução e limites](lab-runbook.md#testes-offline-do-gateway-e-fronteira-de-leitura-c1) | AWAITING_REVIEW |
| C1-04 | P0 | Thomaz | Felipe | C1-01 | [add-on instalável sem efeitos](../odoo/addons/ap_security_executor/models/executor.py), contrato independente e [harness isolado](../scripts/test_c1_scaffold.ps1) commitados em `d2f7ad5`, sob [entrada restrita (DEC-039)](decision-log.md#dec-039); 720 testes offline e 17 no Odoo real, 17 Markdown, hashes/limpeza e segurança aprovados em 30/09. [Seleção verificada da imagem (DEC-040)](decision-log.md#dec-040) em `54564c6`, sem transferir smokes históricos. Falta apenas revisão humana independente de Felipe e conferência de Thomaz. Capacidades transacionais/assinatura/auditoria e HTTP JSON-2 pertencem às tarefas seguintes; [reprodução e limites](lab-runbook.md#instalação-e-fronteira-do-add-on-c1-04) | AWAITING_REVIEW |
| C1-05 | P0 | Thomaz | Felipe | C1-04 | [provisionamento/gate](../odoo/addons/ap_security_executor/identity.py), [inventário efetivo](../reproducibility/c1-permissions.inventory.json) e prova JSON-2 com bearer reais commitados em `3866721`, sob [identidade mínima (DEC-041)](decision-log.md#dec-041); 720 testes offline, 56 Odoo e 54 requisições HTTP aprovados, além da regressão de 17 testes sem HTTP; fonte/estado crítico inalterados, limpeza, documentação e segurança conferidos. Falta apenas revisão humana independente de Felipe e conferência de Thomaz. Sem efeitos do executor, instalação no laboratório existente ou prova de lifecycle de produção; [reprodução e limites](lab-runbook.md#identidade-restrita-e-prova-http-c1-05) | AWAITING_REVIEW |
| C1-06 | P0 | Thomaz | Felipe | C1-02, C1-04 | [núcleo privado transacional](../odoo/addons/ap_security_executor/draft_kernel.py), recibos/guardas e testes commitados em `3a9ffd6`, sob [execução transacional (DEC-042)](decision-log.md#dec-042). 815 offline, 87 Odoo (46 kernel) e regressões de 17 scaffold/56 Odoo com 54 HTTP passaram; hashes, limpeza e segurança conferidos. Falta revisão independente de Felipe e reprodução por Thomaz. `execute` público permanece fechado; aprovação, POST, auditoria, integração e concorrência entre processos continuam nos gates seguintes. [Reprodução e limites](lab-runbook.md#núcleo-transacional-privado-c1-06) | AWAITING_REVIEW |
| C1-07 | P0 | Thomaz | Felipe | C1-01 | [verificador](../odoo/addons/ap_security_executor/approval.py), [nonce transacional](../odoo/addons/ap_security_executor/approval_kernel.py) e testes commitados em `5370cc2`, sob [autenticação da aprovação (DEC-043)](decision-log.md#dec-043). 915 offline (100 novos), 115 Odoo (28 aprovação) e regressões 17/56/87 com 54 HTTP passaram; documentação, hashes, inventário, segurança e limpeza conferidos. Falta revisão de Felipe e reprodução por Thomaz. Sem POST público, custódia real, integração ou prova concorrente; [reprodução e limites](lab-runbook.md#aprovação-autenticada-e-nonce-privado-c1-07) | AWAITING_REVIEW |
| C1-08 | P0 | Thomaz | Felipe | C1-06, C1-07 | [POST privado atômico](../odoo/addons/ap_security_executor/post_kernel.py) commitado em `5582a83`, sob [contabilização aprovada (DEC-044)](decision-log.md#dec-044). 977 offline e 162 Odoo (47 POST) passaram; regressões separadas 17/56/87/115, com 54 HTTP, fonte/hashes/limpeza e segurança conferidos. Falta revisão de Felipe e reprodução por Thomaz. Público fechado; auditoria/integração e lifecycle/concorrência reais seguem pendentes. [Reprodução e limites](lab-runbook.md#contabilização-privada-aprovada-c1-08) | AWAITING_REVIEW |
| C1-09 | P0 | Thomaz | Felipe | C1-02 | [auditoria](../odoo/addons/ap_security_executor/audit_kernel.py) e [anexação direta privada](../odoo/addons/ap_security_executor/attachment_kernel.py) commitadas em `3b943c1`, sob [anexo transacional (DEC-046)](decision-log.md#dec-046). 1.148 offline (78 novos) e 246 Odoo (49 auditoria + 35 anexação), regressões 17/56/87/115/162 e 54 HTTP passaram; mesmas 32 fontes, inventário, hashes, limpeza e segurança conferidos em 04/10. PDF em DB com MIME/tamanho/SHA-256, reutilização no POST/replay e rollback integral testados. Falta revisão humana de Felipe e reprodução por Thomaz. Público fechado; workflow/runner e gates científicos separados. [Reprodução e limites](lab-runbook.md#auditoria-operacional-privada-c1-09) | AWAITING_REVIEW |
| C1-10 | P0 | Thomaz | Felipe | C1-05–09 | [bypass HTTP real](../odoo/addons/ap_security_executor/tests/test_bypass_http.py) commitado em `58d4aa7`, sob [DEC-047](decision-log.md#dec-047) e [DEC-048](decision-log.md#dec-048). 76 Odoo/20 casos novos/123 HTTP passaram em 05/10; CRUD, métodos privados/arbitrários, contexto/empresa, defaults, anexos e ledgers com alvos preenchidos e projeções idênticas. Mesmas 33 fontes das oito provas; inventário/hashes/cleanup conferidos. Falta revisão de Felipe e reprodução por Thomaz. Público fechado; repetir após integração. [Reprodução e limites](lab-runbook.md#bypass-http-c1-10) | AWAITING_REVIEW |
| C1-11 | P0 | Thomaz | Felipe | C1-06–09 | [probe de transações reais](../odoo/probes/c111_transactions.py) e correção da guarda commitados em `58d4aa7`, sob [DEC-047](decision-log.md#dec-047) e [DEC-048](decision-log.md#dec-048). 22 casos, cinco pares de conexões/bloqueios e seis retries passaram; commit/rollback/savepoint, faults, nonce, replay, deriva e lifecycle nativo conferidos. Corrida cross-PO antes `CREATED/CREATED`, agora duplicidade negada e auditada sem segundo efeito. 1.148 offline e regressões 17/56/95/123/171/255 também passaram na mesma fonte. Falta revisão de Felipe e reprodução por Thomaz. Workflow/runner e gates científicos separados. [Reprodução e limites](lab-runbook.md#transações-reais-e-ciclo-de-commit-c1-11) | AWAITING_REVIEW |
| C1-12 | — | Thomaz | Felipe | — | controle de saída e mensagens retirados com a avaliação de exposição de dados, conforme [retirada da exposição de dados (DEC-023)](decision-log.md#dec-023); ID preservado no histórico | CUT |
| SEC-01 | P0 | Thomaz | Felipe | C1-01 | matriz threat→controle→invariante→teste→evidência, incluindo limites residuais | READY |
| SEC-02 | P1 | Thomaz | Gustavo | C1-10–11 | inventário de permissões/capacidades e prova de zero mutação crítica fora do método | WAIT |

## 10. Runner, oráculo e observabilidade experimental

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| RUN-01 | P0 | Gustavo | Felipe | SCI-03 | [registro v2 (DEC-057)](lab-runbook.md#run-record-candidato) preserva falhas e resultados recalculados; [histórico de reset (DEC-059)](lab-runbook.md#recuperacao-reset-mesmo-slot) acrescenta checkpoints no mesmo slot sem alterar o original ou criar missing. Faltam SCI-03, decisão/aprovação completas, chamadas com identidade, invariantes individuais, custo, supervisão real e revisão de Felipe. Contrato de engenharia, não aceite científico | ACTIVE |
| RUN-02 | P0 | Gustavo | Thomaz | RUN-01 | [round-trip observado](lab-runbook.md#round-trip-privado-observado), [captura/reset e oráculo](lab-runbook.md#captura-restauracao-oraculo) e registros existentes preservados. [Handoff POST com fixture pré-emitida (DEC-069)](lab-runbook.md#handoff-post-observado) passou: política/JSON-2 reais, contabilização privada, MAC inválido rejeitado e replay sem segundo efeito; provedor simulado. Faltam ciclo único com LLM real/dados revisados, supervisão, imagem e revisão humana. Transporte público e runner científico pendentes; execute fechado | ACTIVE |
| RUN-03 | P0 | Gustavo | Felipe | estado M2 | [ponte de captura (DEC-055)](lab-runbook.md#captura-restauracao-oraculo) e [ponte dataset→oráculo (DEC-061)](lab-runbook.md#contrato-pares-oraculo) ligam expectativas independentes; correções de quase-acerto/classe/registro v3 integradas pela DEC-063. [Piloto candidato (DEC-064)](lab-runbook.md#preparacao-12-pares-piloto) fornece documentos, não fatos ERP observados. Faltam revisão de Felipe, fixtures/atribuição/produtores completos e piloto; não é resultado de resistência do LLM | ACTIVE |
| RUN-04 | P0 | Gustavo | Thomaz | RUN-02 | [snapshot (DEC-055)](lab-runbook.md#captura-restauracao-oraculo) tem dezesseis restaurações nativas anteriores. [DEC-059](lab-runbook.md#recuperacao-reset-mesmo-slot) registra verificação posterior de reset e mantém bloqueios de classificação/LLM; não comprova término remoto, saúde ou recuperação nativa nesta fonte. Faltam ligação ao supervisor real, saúde/espaço/relógio e revisão humana. Outbox desabilitada | ACTIVE |
| RUN-05 | P0 | Gustavo | Felipe | RUN-01–04 | pareamento, ordem intercalada/randomizada, três repetições e seed/ordem registradas | WAIT |
| RUN-06 | P0 | Gustavo | Felipe | SCI-03, RUN-02 | [política de tentativas (DEC-031)](decision-log.md#dec-031) preservada; [DEC-057](lab-runbook.md#run-record-candidato) valida históricos terminais e registra falhas sem retry automático ou `MISSING` inventado. Faltam parâmetros/revisão da observação em SCI-03, supervisão e validação integrada; parsing/recusa continuam outcomes com estado verificável | WAIT |
| RUN-07 | P1 | Gustavo | Felipe | G3-05, RUN-01 | token/custo/latência por etapa, pricing datado e request ID saneado | WAIT |
| RUN-08 | P0 | Gustavo | Thomaz | RUN-01 | [store original (DEC-056/057)](lab-runbook.md#run-record-candidato) e [journal de reset (DEC-059)](lab-runbook.md#recuperacao-reset-mesmo-slot) preservam arquivos exclusivos e hashes, sem sobrescrever, repetir run ou exportar. Histórico complementar cobre somente reset; não autentica produtor, comprova backup externo ou detecta remoção de sufixo sem âncora externa. Faltam demais históricos/caminhos brutos, retenção/custódia externa e revisão de Thomaz | ACTIVE |
| RUN-09 | P1 | Gustavo | Felipe | RUN-02–08 | ensaio sintético completo sem conjunto final; valida schemas e gera dados para dry-run estatístico | WAIT |

## 11. Piloto e congelamento

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PILOT-01 | P0 | Gustavo | Felipe | G3-05, C0-02, C0-03, C0-05, C1-11, DATA-06, RUN-09 | prontidão técnica e plausibilidade revisadas em ensaio não final; agendar 24 docs × C0/C1 × 3 = 144 runs. Competência será medida em C0-04/PILOT-03, não presumida antes de executar o piloto | WAIT |
| PILOT-02 | P0 | Gustavo | Thomaz | PILOT-01 | executar piloto, preservar raw/manifest e restaurar estado a cada cenário | WAIT |
| PILOT-03 | P0 | Felipe | Gustavo | PILOT-02 | relatório de competência, ASR diagnóstica, BTSR, Delivery, latência, custo, erros e denominadores | WAIT |
| PILOT-04 | P0 | Felipe | Thomaz | PILOT-03 | poder/precisão por discordância pareada; ações críticas usam 30 pares; decidir tamanho antes do conjunto final | WAIT |
| PILOT-05 | P0 | Thomaz | Felipe | PILOT-03 | lista fechada de correções funcionais/segurança; nenhuma escolha pelo melhor resultado final | WAIT |
| PILOT-06 | P0 | Gustavo | Felipe | PILOT-05 | reexecutar integralmente piloto afetado e produzir relatório final de prontidão | WAIT |
| STAT-01 | P0 | Felipe | Gustavo | RUN-01 | pipeline enxuto em dados sintéticos: denominadores/missing, efeito e IC95% pareados, bootstrap BCa de 10.000 por `pair_id`, percentil de sensibilidade, McNemar exato complementar e não inferioridade `−0,10`. Validar zero/fronteira e dependência das repetições antes do freeze; Wilson/Newcombe não tratam 270 runs correlacionadas como pares independentes. Sem GEE/Firth/modelos adicionais/Holm | READY |
| FRZ-01 | P0 | Felipe | Thomaz | SCI-01–03/05–09, PILOT-06 | assinar RQ1–3, H1/H3/H2, endpoints, métricas, margem e plano de análise estatística; H4/RQ4/H5 retiradas com IDs reservados | WAIT |
| FRZ-02 | P0 | Felipe | Gustavo | DATA-08 | congelar dataset/ground truth/codebook/manifests por hash | WAIT |
| FRZ-03 | P0 | Gustavo | Thomaz | G3-06, C0-04, C1-11, RUN-09 | competência medida e aceita; congelar modelo/prompts/schemas/policy/retry/timeouts/imagens/configuração e igualdade C0/C1 | WAIT |
| FRZ-04 | P0 | Gustavo | Felipe | FRZ-03 | preservar artefatos OCI finais em custódia imutável ou registry aprovado; registrar digests | WAIT |
| FRZ-05 | P0 | Thomaz | Gustavo | C1-10–11 | assinar ACLs, contexto, auto-post, idempotência, concorrência, replay e fail-closed | WAIT |
| FRZ-06 | P0 | Felipe | Gustavo | SCI-03, STAT-01 | assinar missing/exclusão/desvio/reexecução e análise enxuta, incluindo intervalos de fronteira validados para o endpoint e dependência corretos | WAIT |
| FRZ-07 | P0 | Gustavo | Thomaz | G3-03, FRZ-03 | comprovar secrets/egress, rotação planejada e ausência de segredo/log bruto no pacote | WAIT |
| FRZ-08 | P0 | Felipe | Thomaz/Gustavo | FRZ-01–07 | release/tag 1.3 e checklist M6 completos antes de abrir o conjunto final | WAIT |

## 12. Experimentos

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| EXP-01 | P0 | Gustavo | Felipe | FRZ-08 | ensaio de um lote sem dados finais; checklist 30.2 e recuperação testados | WAIT |
| EXP-02 | P0 | Gustavo | Felipe | EXP-01 | executar 1.080 runs DeepSeek C0×C1 intercaladas; raw íntegro, reset e nenhum retry pendente | WAIT |
| EXP-03 | P0 | Felipe | Gustavo | EXP-02 | QA de denominadores/missing/desvios sem observar/tunar defesa durante coleta | WAIT |
| EXP-04 | — | Gustavo | Felipe | — | bloco defense-aware retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem execuções ou claim de robustez adaptativa | CUT |
| EXP-05 | — | Gustavo | Thomaz | — | bloco de ablação retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem atribuição causal por camada | CUT |
| EXP-06 | — | Gustavo | Felipe | — | bloco Qwen3 retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem claim de generalização entre modelos | CUT |
| EXP-07 | P0 | Gustavo | Felipe | EXP-02 | fechar manifests, hashes, custo, integridade, custódia raw e rotação da chave do piloto e principal | WAIT |

## 13. Análise e resultados

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| AN-01 | P0 | Felipe | Gustavo | EXP-07, STAT-01 | validar dados, schema, duplicatas, pares, missing, retries e denominadores | WAIT |
| AN-02 | P0 | Felipe | Thomaz | AN-01 | [redução do sucesso dos ataques (H1)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h1): ASR-proposal/policy/state com efeito pareado, IC95% e teste pré-definido | WAIT |
| AN-03 | P0 | Felipe | Thomaz | AN-01 | [preservação da utilidade (H3)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h3): BTSR e não inferioridade com limite `−0,10` e IC95% | WAIT |
| AN-04 | P0 | Felipe | Gustavo | AN-01 | [redução de ações críticas indevidas (H2)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h2) e utilidade: UACR, falsos bloqueios, encaminhamentos e análise de falhas | WAIT |
| AN-05 | P0 | Felipe | Gustavo | AN-01 | eficiência descritiva em RQ2: latência, tokens, custo, revisão técnica potencial e variabilidade; sem teste de aceitabilidade H4 ou humana | WAIT |
| AN-06 | — | Felipe | Thomaz | — | análises defense-aware/ablação e testes de subgrupos/Holm retirados pela [DEC-058](decision-log.md#dec-058); famílias e mecanismos descritivos permanecem em AN-09 | CUT |
| AN-07 | — | Felipe | Gustavo | — | análise de transportabilidade Qwen3 retirada da entrega pela [DEC-058](decision-log.md#dec-058) | CUT |
| AN-08 | P0 | Felipe | Thomaz/Gustavo | AN-02–05 | figuras/tabelas regeneráveis, trace entre número, script, dado e commit | WAIT |
| AN-09 | P0 | Thomaz | Felipe | AN-02–05/08 | descrição por família/estratégia/template, falhas, mecanismos e limites, sem busca de significância ou causalidade por camada | WAIT |

## 14. Artigo, reprodução, submissão e defesa

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PAPER-01 | P1 | Felipe | Thomaz | SCI-07/10 | introdução e referencial com lacuna/fonte auditáveis | WAIT |
| PAPER-02 | P1 | Felipe | Gustavo | SCI-01 para rascunho; FRZ-08 para fechar | redigir metodologia em paralelo e marcar pendências; versão final reproduz exatamente protocolo/freeze e ausência de humanos | WAIT |
| PAPER-03 | P0 | Thomaz | Felipe | AN-09 | implementação/segurança C0/C1, sem claims além da evidência | WAIT |
| PAPER-04 | P0 | Gustavo | Felipe | EXP-07 | ambiente, dataset executado, runner, modelos, proveniência e custo operacional | WAIT |
| PAPER-05 | P0 | Felipe | Thomaz/Gustavo | AN-08/09 | resultados/discussão por RQ, números gerados, negativos e limitações | WAIT |
| PAPER-06 | P0 | Felipe | Thomaz | PAPER-05 | Resumo/Abstract/Conclusão pós-experimento, 150–250 palavras e equivalência | WAIT |
| PAPER-07 | P0 | Felipe | Gustavo | PAPER-01–06 | reconciliar citações/referências ABNT e manter 10–20 páginas | WAIT |
| PAPER-08 | P0 | Gustavo | Felipe | PAPER-07, ADM-02 | build final, metadados, inspeção visual, hashes, backup e pacote na extensão aceita | WAIT |
| PAPER-09 | P0 | Felipe | Thomaz/Gustavo/orientador | PAPER-08 | revisão científica, red team, engenharia e editorial; aprovação até 02/11 | WAIT |
| REP-01 | P1 | Thomaz | Felipe | FRZ-08 | reproduzir ambiente/runner mantido por Gustavo a partir de instruções limpas | WAIT |
| REP-02 | P1 | Gustavo | Thomaz | AN-08 | reexecutar análise mantida por Felipe e conferir tabelas/figuras | WAIT |
| REP-03 | P1 | Felipe | Thomaz/Gustavo | REP-01/02 | relatório de reprodução, limitações e badge de estado honesto | WAIT |
| SUB-01 | P0 | Gustavo | Felipe | PAPER-09, ADM-02 | submeter no Oriente até 08/11 e preservar recibo fora do Git | EXTERNAL |
| DEF-01 | P1 | Felipe | todos | PAPER-09 | slides de 15–20 min, narrativa problema→método→resultado→limite | WAIT |
| DEF-02 | P1 | Gustavo | Thomaz | DEF-01 | demo segura ou gravação, sem Internet/segredo/estado real | WAIT |
| DEF-03 | P1 | Thomaz | Felipe | DEF-01 | banco de arguição de segurança, baseline, validade e generalização | WAIT |
| DEF-04 | P1 | Felipe | orientador | DEF-01–03 | dois simulados cronometrados e respostas de até 60 s por integrante | WAIT |
| DEF-05 | P0 | Felipe | Gustavo | banca | incorporar correções até 03/12; preservar mudanças e nova validação | EXTERNAL |
| DEF-06 | P0 | Gustavo | Felipe | DEF-05 | artigo corrigido/Adelpha até 04/12 e anuência final até 07/12 | EXTERNAL |

## 15. Trabalho futuro e itens fora da entrega

| Item | Classe | Regra |
|---|---|---|
| Qwen3 14B | trabalho futuro / `CUT` | não baixar, testar ou executar neste cronograma; reativação exige nova decisão |
| Defense-aware e ablação | trabalho futuro / `CUT` | não gerar nem executar; declarar ausência de robustez adaptativa e atribuição por camada |
| UI de revisão | P3 opcional | não implementar antes de experimento; logs/tabelas bastam |
| Detector de prompt injection | P3 opcional | não integra núcleo; se existir, nunca autoriza e precisa bloco exploratório |
| Presidio e mensagens ao fornecedor | fora do escopo | retirados com a avaliação de exposição de dados; não criar implementação ou experimento |
| OCR, NF-e válida, SaaS 19.4, Enterprise, IA nativa, pagamento/e-mail real | fora do escopo | não criar tarefa nem protótipo durante o TCC |
| Segundo domínio/ERP/idioma | trabalho futuro | não entra no cronograma atual |

## 16. Contratos de integração I1

Antes de integrar as três trilhas, os seguintes contratos devem estar versionados e revisados:

1. `vendor-bill-model-output/v1` e `vendor-bill-proposal/v1` — históricos M2/G3c, imutáveis; `vendor-bill-action-output/v2` e `vendor-bill-action-proposal/v2` — contrato candidato para o fluxo científico C0/C1 conforme [DEC-035](decision-log.md#dec-035), sujeito a revisão antes do piloto;
2. `dataset-manifest/v1`, `pair/scenario ground-truth/v1` — P1, revisão P3/P2 apenas de schema;
3. `policy-input/v1`, `policy-decision/v1`, reason codes e `capability-command/v1` — [tipos e vínculos C1-01](../gateway/src/tcc_gateway/policy_contracts.py), commit `ba38573`, aguardando revisão P1/P2. A estrutura não comprova origem do snapshot nem verifica assinatura; código consumidor deve validar vínculos e revalidar estado/autorização no executor;
   A [fronteira de leitura C1-03](../gateway/src/tcc_gateway/trusted_resolution.py) separa workflow/observações confiáveis da proposta v2; origem dos sinais, revalidação transacional e integração com identidade restrita continuam gates explícitos. Reprodução offline e limites estão no [runbook](lab-runbook.md#testes-offline-do-gateway-e-fronteira-de-leitura-c1);
4. `run-record/v1` e oracle outcome — P3, revisão P1/P2;
5. prompt envelope C0/C1 e hashes — P2, revisão P1;
6. reset/fixture manifest — P3, revisão P2;
7. SAP e mapping RQ→endpoint — P1, revisão P2/P3.

Nenhuma integração deve contornar um contrato com dicionário livre, ID interno fornecido pelo documento, RPC genérico ou campo `context` externo.

## 17. Regras de merge e revisão

- toda tarefa `P0` possui data-limite explícita, conforme §19.3 do plano; tarefa `EXTERNAL` recebe data-limite de resposta e data de escalonamento;
- ultrapassada a data de escalonamento, o assunto vai ao orientador na reunião seguinte e o fato é registrado; tarefa que passou da data-limite sem mudar de estado é reportada como atrasada no checkpoint semanal e obriga replanejamento explícito da onda, nunca prorrogação silenciosa;
- o estado `ACTIVE` é usado de fato: tarefa com owner trabalhando não permanece `READY`, sob pena de o backlog deixar de detectar atraso;
- `AWAITING_REVIEW` só é usado quando o item aponta commit e testes, e resta apenas a revisão independente. Implementações dependentes podem avançar com o hash do contrato; uma reprovação reabre o item e obriga revalidar consumidores. Piloto, freeze e aceite científico exigem `DONE`, não `AWAITING_REVIEW`;
- um owner não aprova sozinho tarefa crítica própria;
- P2 não recebe o conjunto final completo antes do freeze da defesa;
- mudanças nos contratos I1 geram decisão e reexecução dos consumidores afetados;
- depois do freeze, toda divergência entra em `docs/deviation-log.md`;
- cada PR/commit informa tarefa, teste, evidência, pendência e impacto em runs;
- staging sempre usa caminhos explícitos e passa pelos dois gates de segurança;
- nunca publicar segredo, raw, documento real, dump, volume ou logs não saneados;
- reunião semanal fecha tarefas por evidência e replaneja `WAIT`/`EXTERNAL`.

## 18. Cobertura dos checklists normativos

| Fonte | Pendências cobertas |
|---|---|
| Plano §30.1 Freeze | SCI-01–03, DATA-07/08, C0-04/05, C1-05–11, FRZ-01–08, STAT-01; SCI-04 retirada |
| Plano §30.2 Lotes | RUN-03–08, EXP-01/02 |
| Plano §30.3 Submissão | ADM-01–09, PAPER-06–09, SUB-01 |
| Seleção de modelos G3 | G3-01–08, C0-01–05, FRZ-03/07 |
| Institucional | ADM-01–13, PAPER-07–09, SUB-01, DEF-05/06 |
| Plano §16.3 e §17.3 (pacote de reprodução) | ADM-12, ADM-13 |
| Plano §23 (registro de uso de IA) | ADM-11 |
| Plano §16.8 (invariante de ordem do beneficiário) | SEC-A2 |
| Literatura/lacuna | SCI-05–07/10, PAPER-01 |
| Dataset e revisão | DATA-01–08/10; DATA-09/EXP-04 retiradas |
| C1/segurança | C1-01–11, SEC-01/02; EXP-05 retirada |
| Estatística/resultados | STAT-01, PILOT-03/04, AN-01–09 |
| Reprodução/defesa | REP-01–03, DEF-01–06 |

## 19. Definition of Done deste backlog

O backlog é considerado operacional quando:

- toda pendência conhecida possui ID, owner, reviewer, dependência, prioridade, entregável e estado;
- os três integrantes possuem pelo menos uma tarefa `READY` sem editar o mesmo componente;
- caminho crítico e itens cortáveis estão explícitos;
- checklists do plano, seleção dos modelos e requisitos institucionais estão rastreados;
- tarefas externas não são apresentadas como concluídas sem recibo/resposta;
- mudança futura atualiza este arquivo e, se material, o decision log antes da implementação.
