# Backlog operacional completo do TCC II

**Decisão de ownership:** [divisão do trabalho (DEC-021)](decision-log.md#dec-021)

**Data-base:** 27/10/2026

**Estado científico:** [plano v1.2.21 / estudo descritivo (DEC-094)](decision-log.md#dec-094). A entrega avalia **144 execuções no Odoo: 12 pares × 2 documentos × C0/C1 × 3 repetições**. Os 90 pares e 1.080 runs adicionais estão retirados. Não há testes de superioridade ou não inferioridade; 10 pontos percentuais é referência de utilidade.

**O que está liberado:** C0, contratos/dados, preparo ERP e controles têm os pareceres indicados nas tabelas. A coorte `.4` passou por conferência de 12 bases, cinco bancos, oito origens A3a e 16 restaurações. A anuência está aprovada por confirmação de Gustavo; 607 arquivos de propostas receberam cópia local criptografada com restauração conferida.

**As 144 execuções terminaram e passaram na [revisão independente](reviews/2026-10-27-piloto-concluido.md).** Agenda, envelopes, capturas, aprovação, restaurações, denominadores e intervalos foram conferidos; nenhum motivo para repetir a coleta. **A cópia criptografada dos 20.678 arquivos também terminou com restauração verificada. Agora:** incorporar resultados/figuras no artigo, fechar o pacote de reprodução e obter o aceite final. Revisão automatizada não é assinatura humana ou freeze retroativo. A execução parcial anterior permanece separada.

**Leitura dos códigos:** [C0](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#c0) é a integração direta; [C1](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#c1), a integração protegida. RQ significa pergunta de pesquisa; H, hipótese; DEC, decisão registrada. Os links levam ao significado completo. Consulte a [leitura rápida](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#leitura-rapida) antes de iniciar uma tarefa.

## 1. Como usar este backlog

Este arquivo é a fila única de trabalho restante. Uma tarefa só muda para `DONE` quando o entregável e a Definition of Done (DoD) indicados existem e foram revisados. Percentual subjetivo, código sem teste, texto sem fonte ou execução sem manifest não concluem tarefa.

Estados permitidos:

- `READY`: pode começar sem aguardar outra tarefa;
- `ACTIVE`: possui owner trabalhando e próximo checkpoint definido;
- `AWAITING_REVIEW`: artefato, testes, documentação e evidência técnica não dependente de revisão estão completos e commitados; falta somente revisão/assinatura independente. Permite iniciar dependentes de engenharia sobre contrato versionado, mas **não** satisfaz gates de piloto, freeze ou resultado científico; ver [regra de aceite intermediário (DEC-034)](decision-log.md#dec-034);
- `AGENT_REVIEWED`: revisado por agente distinto do autor, com contraexemplos executados e achados tratados ([DEC-081](decision-log.md#dec-081)); falta a assinatura humana nominal. Satisfaz a revisão independente para **iniciar o piloto**, mas não a assinatura de freeze;
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
componentes revistos + coorte .4 ──→ 144 execuções Odoo ──→ conferência/intervalos
literatura + método + arquitetura ───────────────────────→ resultados/artigo → aceite/submissão
```

As janelas são alvos condicionados à evidência; não autorizam reduzir repetições, relaxar C1 ou selecionar resultados.

| Janela-alvo em 2026 | Felipe — ciência e artigo | Thomaz — segurança | Gustavo — execução | Saída |
|---|---|---|---|---|
| 27–28/10 | validar denominadores e intervalos; consolidar literatura/método | conferir limites dos controles e revisar a integração | concluir/conferir piloto integrado, restaurar estado e preservar brutos | 144 slots íntegros ou interrupção declarada |
| até 01/11 | resultados, discussão, Resumo/Abstract | revisar arquitetura, falhas e conclusões | conferir manifests, custo, reprodução e pacote | artigo completo com números rastreáveis |
| 02/11 | revisão científica/editorial | revisão de segurança | revisão de reprodução e build | aceite interno e reaberturas resolvidas |
| até 08/11 | ajustes e declaração institucional de IA | conferir conclusões finais | submissão e recibo | entrega aceita, sem presumir prorrogação |
| 10/11–07/12 | slides e correções | demonstração/arguição de segurança | demonstração/ambiente | banca e versão final |

Qwen3, ablação, defense-aware e o corpus adicional de 90 pares são trabalho futuro. A análise preserva três repetições dependentes, pareamento, intervalos por par e tratamento explícito de ausências/fronteiras; não aplica testes confirmatórios.

## 4. O que fazer agora — três trilhas paralelas

Usar os IDs das tabelas como fila única. As revisões de componentes não precisam ser refeitas. O artigo é editado em paralelo pela outra sessão; esta frente preserva suas alterações.

| Integrante | Próximas tarefas | Critério para avançar |
|---|---|---|
| Felipe | AN-05/08, PAPER-01/02/05–07, ADM-02/11 | denominadores e intervalos conferidos; resultados descritivos; declaração de IA e limites no artigo |
| Thomaz | AN-09, PAPER-03, revisão das conclusões e reprodução | efeito, aprovação, reset e conclusões coerentes com os controles já revistos; sem expansão da defesa |
| Gustavo | RUN-07/08, DATA-10, EXP-07, PAPER-04/08, ADM-09 | execução íntegra, custódia conferida, manifests/custo e pacote reproduzível |

Não reiniciar coleta, ajustar notas/prompt/política ou mudar as fontes monitoradas durante o piloto. Pareceres por agente têm escopo/hashes explícitos; aceite do grupo e aprovação do artigo permanecem separados.

## 5. Administração e requisitos institucionais

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| ADM-01 | P0 | Felipe | Gustavo | — | obter Regulamento Geral e Guia Geral vigentes; registrar origem/hash sem PII | READY |
| ADM-02 | P0 | Felipe | Thomaz | — | confirmar no Oriente extensão de arquivo, política/declaracão de IA e preservar resposta saneada. Edital V4 (27/10) define a declaração de IA: Anexo I da RE-CONSU-017/2026, assinado pelos três alunos e pelo orientador e anexado ao final do artigo ([requisitos](institutional-requirements.md)). Falta preencher/assinar e confirmar extensão do arquivo e se o anexo conta nas 20 páginas. Em 29/10, Felipe informou o edital V5, que mantém a declaração e não esclarece extensão nem contagem do anexo; o formulário foi preenchido e depois removido, e falta o PDF gerado e as assinaturas ([auditoria](reviews/2026-10-29-auditoria-felipe.md)). Em 31/10: V5 registrado com hash; submissão em PDF e anexo fora das 20 páginas, informados por Gustavo; respostas do formulário rascunhadas em [respostas da declaração de IA](declaracao-ia-respostas.md). Falta enviar o formulário, baixar o PDF e colher as quatro assinaturas. | EXTERNAL |
| ADM-03 | P0 | Felipe | Gustavo | — | confirmar janela/horários/eligibilidade PPI/PPP/PPA e anomalia `31/11`; atualizar matriz. O V5 (31/10) corrigiu a data para 30/11/2026; faltam horários e elegibilidade. | EXTERNAL |
| ADM-04 | P0 | Felipe | Gustavo | — | confirmar dados institucionais e alinhamento do tema à área/projeto do orientador | EXTERNAL |
| ADM-05 | P0 | Felipe | Thomaz | — | instituir registro semanal/quinzenal de orientação com pauta, presença, decisões e próximos passos | READY |
| ADM-06 | P0 | Felipe | Gustavo | — | Anuência aprovada, confirmada por Gustavo nesta conversa em 26/10/2026; [DEC-091](decision-log.md#dec-091). Não houve consulta automatizada ao Oriente. Recibo e data efetiva ainda não fornecidos; acompanhamento documental em ADM-09. Manifesto privado da confirmação: SHA-256 `140dfc71…`. | DONE |
| ADM-07 | P0 | Gustavo | Felipe | — | cadastro do projeto e três autores confirmados; evidência privada de 01/09 preservada por hash no lock institucional, sem identificadores no Git | DONE |
| ADM-08 | P0 | Gustavo | Felipe | ADM-07 | requerimento protocolado em 01/09, três autores conferidos e evidência privada preservada por hash no lock institucional | DONE |
| ADM-09 | P1 | Gustavo | Felipe | ADM-02 | Manter calendário/avaliadores/banca/correções; obter recibo da anuência já confirmada em ADM-06 e as informações externas ADM-02/03. Não escalar aprovação como pendente. | ACTIVE |
| ADM-10 | P0 | Felipe | Thomaz | [divisão do trabalho (DEC-021)](decision-log.md#dec-021) | atualizar requisitos institucionais com papéis nominais; disponibilidade revista semanalmente | DONE |
| ADM-11 | P0 | Felipe | Thomaz | — | manter `docs/ai-usage.md` atualizado a cada release do plano e a cada seção do artigo; derivar dele a declaração institucional quando ADM-02 responder, sem reconstruir de memória | ACTIVE |
| REP-05 | P1 | Gustavo | Thomaz | FRZ-08 | reexecutar a suíte de segurança de C1 em ambiente limpo e registrar tentativa independente de bypass, fechando o ciclo de reprodução dos três componentes | WAIT |
| LIC-01 | P1 | Felipe | Thomaz | ADM-12 | criar `docs/licensing.md` fixando LGPL-3.0-or-later para o add-on derivado do Odoo, licença aberta para gateway/runner/análise e licença própria para o dataset, com compatibilidade verificada contra `gateway/constraints.txt` | READY |
| ADM-12 | P1 | Felipe | Thomaz | — | escolher e adicionar `LICENSE` para código, dataset e documentação, com compatibilidade verificada contra a LGPLv3 do Odoo e as licenças das dependências; registrar a justificativa no decision log | READY |
| ADM-13 | P1 | Felipe | Gustavo | ADM-12 | criar `CITATION.cff` e a seção de instruções de citação no README; conferir contra o checklist de §17.3 do plano | READY |
| SEC-A2 | P0 | Thomaz | Gustavo | — | implementar no executor e no runner a assertion que impede escrita de `partner_id` depois de `partner_bank_id`, conforme o invariante de §16.8 e o resultado do `T-A2-PREFREEZE`. Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |

## 6. Protocolo científico e literatura

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| SCI-01 | P0 | Felipe | Thomaz | — | Protocolo e denominadores revistos; [versão operacional](protocol.md) reconciliada com o estudo descritivo DEC-094/097. [Parecer dos componentes](reviews/2026-10-26-ciencia-operacional.md). Sem testes H1/H2/H3 ou corpus adicional; aceite da evidência em FRZ, sem assinatura inventada. | AGENT_REVIEWED |
| SCI-02 | P0 | Felipe | Gustavo | — | Referência de 10 pontos percentuais explicada no [protocolo](protocol.md): dez tarefas adicionais não concluídas por cem em relação a C0, diferença absoluta. [Revisão](reviews/2026-10-26-literatura.md). Pela DEC-094, não é critério de não inferioridade; sem validação empresarial ou recalibração. | AGENT_REVIEWED |
| SCI-03 | P0 | Felipe | Thomaz | — | Classificador e produtor candidato de três leituras foram testados/revistos ([DEC-087](decision-log.md#dec-087)); não estão integrados ao piloto DEC-095. O runner atual para se captura/estado/reset falham, sem fabricar MISSING. Declaração explícita no [protocolo](protocol.md); integração do retry fica posterior, sem bloquear coleta íntegra. Regra conservadora e classificação revistas; os registros completos do lote continuam em RUN-02/09. O retry opcional não é uma pendência bloqueante. | AGENT_REVIEWED |
| SCI-04 | — | Felipe | Gustavo | — | hipótese de aceitabilidade H4 retirada pela [DEC-058](decision-log.md#dec-058), ID reservado. Medição descritiva permanece em RUN-07/AN-05; não escolher limites confirmatórios | CUT |
| SCI-05 | P0 | Felipe | Thomaz | — | Procedimento dirigido executado com consultas, origem e datas reais; sem alegação sistemática/exaustiva. [verificação primária](literature-review.md) e [parecer](reviews/2026-10-26-literatura.md). | AGENT_REVIEWED |
| SCI-06 | P0 | Felipe | Thomaz | SCI-05 | Oito comparadores primários e contraexemplos recentes em matriz de ameaça/ambiente/defesa/métricas/reprodução/limites. [verificação primária](literature-review.md). Acesso parcial e artefatos não confirmados declarados; nenhum resultado final consultado. | AGENT_REVIEWED |
| SCI-07 | P0 | Felipe | Thomaz | SCI-06 | Formulação candidata da contribuição como avaliação contextualizada/replicável de ERP e efeitos transacionais; AgentDojo já mede estado e autorização externa tem precedentes. [verificação primária](literature-review.md). Sem claim de primeiro/ausência de equivalente; ratificação de freeze permanece FRZ-01. | AGENT_REVIEWED |
| SCI-08 | P1 | Felipe | Gustavo | SCI-03 | registrar ética, ausência de participantes, custódia raw, retenção e revisão dupla de exports | READY |
| SCI-09 | P1 | Felipe | Thomaz | SCI-01 | [Matriz de rastreabilidade](control-test-matrix.md): pergunta, endpoint, denominador, teste e saída descritiva; três repetições dependentes e IC por par, sem hierarquia confirmatória. [Parecer](reviews/2026-10-26-ciencia-operacional.md), com reconciliação DEC-097. | AGENT_REVIEWED |
| SCI-10 | P1 | Felipe | Gustavo | SCI-05 | 20 entradas e 20 chaves citadas no artigo, sem órfã/ausente; fontes primárias conferidas e limites de acesso explícitos em [verificação primária](literature-review.md). Bibliografia preservada; novas alegações do artigo exigem citação correspondente. | AGENT_REVIEWED |

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
| A3A-01 | P0 | Gustavo | Thomaz e Felipe | [contrato de ação v2 (DEC-035)](decision-log.md#dec-035) | schemas, adapters e [transporte/consumidores v2 (DEC-050)](decision-log.md#dec-050) preservados. [Prova nativa (DEC-051)](decision-log.md#dec-051) confirma POST C0 sem aprovação no alvo confiável, sem reescrever campos propostos. Faltam revisão independente e aceite da semântica A3a; não é taxa de ataques. Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C0-01 | P0 | Thomaz | Felipe | SCI-01, G3a | Prompt-base/fases comuns, sem condição no construtor, revisados sob DEC-083/087. 24 grupos de requisições idênticas C0/C1 e payload permanece no papel user; [revisão independente](reviews/2026-10-26-c0-dados.md). Ratificação nominal e freeze continuam próprios. | AGENT_REVIEWED |
| C0-02 | P0 | Thomaz | Gustavo | C0-01, A3A-01 | Consumidor v2, sete casos nativos DEC-051 e contraprovas de valor/beneficiário/POST revistos; C0 preserva argumentos sem aplicar regras C1. [revisão independente](reviews/2026-10-26-c0-dados.md). A composição da coorte/estado segue RUN-02 e competência medida segue C0-04; não é piloto concluído. | AGENT_REVIEWED |
| C0-03 | P0 | Thomaz | Gustavo | C0-01 | Capacidades restritas ao escopo: rascunho e contabilização, sem pagamentos/e-mail reais. Prompt/fase e transporte separados e revistos em [revisão independente](reviews/2026-10-26-c0-dados.md). Configuração nominal de freeze pendente. | AGENT_REVIEWED |
| C0-04 | P0 | Thomaz | Felipe | C0-02, DATA-05, G3-05, PILOT-02 | Competência benigna medida no ERP: 36/36 tarefas C0 concluídas; dados/denominadores cruzados com registros na [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Resultado descritivo, sem ajuste ao limiar ou nova coleta. | AGENT_REVIEWED |
| C0-05 | P0 | Felipe | Gustavo | C0-02, C0-03 | Plausibilidade estrutural revista: prompt comum, identidade funcional e ausência de regras de negócio C1 em C0. [Revisão](reviews/2026-10-26-c0-dados.md) e [parecer](reviews/2026-10-26-ciencia-operacional.md). Competência e efeitos são medidos em C0-04/PILOT; o enquadramento descritivo já foi adotado pela DEC-094. | AGENT_REVIEWED |

## 8. Dataset, ground truth e red team

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| DATA-01 | P0 | Felipe | Gustavo | contrato atual | Contrato de pares, fatos compartilhados, hashes, unicidade e ponte tipada para o oráculo revistos. [revisão independente](reviews/2026-10-26-c0-dados.md). Bindings candidatos .4 conferidos sob DEC-090; composição com execuções segue RUN-02/09 e separação/revisão do corpus final segue DATA-07/08. | AGENT_REVIEWED |
| DATA-02 | P0 | Felipe | Thomaz | threat model | Codebook/taxonomia/fatos e ausência de autoridade em labels revistos; origens/aprovações distintas por proveniência conferidas em DEC-090. [revisão independente](reviews/2026-10-26-c0-dados.md). Bytes do codebook preservados para manter os hashes da coorte; comentários antigos de prontidão são snapshot histórico, não estado operacional corrente. | AGENT_REVIEWED |
| DATA-03 | P0 | Felipe | Thomaz | DATA-01 | [gerador candidato (DEC-062)](lab-runbook.md#geracao-pdfs-desenvolvimento), implementado por Gustavo em contingência: T1/T2/T3, marca por página, extração/hashes e gravação/releitura exclusiva em `.runtime`; somente desenvolvimento. 4.091 testes e dez páginas inspecionadas; faltam revisão técnica de Thomaz e adequação documental por Felipe, sem autorrevisão. Não equivale a dataset revisado. Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| DATA-04 | P0 | Felipe | Thomaz | DATA-01–03 | Coorte candidata .4: 12 pares/24 PDFs revistos quanto a fatos, notas e ausência de vazamento assimétrico, sem abrir resultados da rodada 2. [revisão independente](reviews/2026-10-26-c0-dados.md). Não é dataset final, publicação de payloads ou piloto de estado executado; versões anteriores preservadas. | AGENT_REVIEWED |
| DATA-05 | P0 | Gustavo | Felipe | DATA-04, G3-04 | Entrada/wire conferidos: 24 PDFs, notas íntegras após extração e 144 corpos de requisição com transporte simulado; bytes comuns C0/C1. [revisão independente](reviews/2026-10-26-c0-dados.md). Medidas de cada chamada efetiva continuam no relatório do piloto; não se infere atenção interna do provedor. | AGENT_REVIEWED |
| DATA-06 | P0 | Gustavo | Felipe | DATA-04 | Preparo ERP .4 revisto sob [DEC-090](decision-log.md#dec-090): 12 bases, cinco bancos, oito origens e aprovações em memória, 25 capturas/16 restaurações; fatos, IDs e hashes conferidos por [parecer operacional](reviews/2026-10-26-ciencia-operacional.md). Não ratifica perfil operacional nem ciclo LLM/estado: RUN-02/09 e SCI-03 permanecem gates. | AGENT_REVIEWED |
| DATA-07 | P0 | Felipe | Gustavo | PILOT-04 | gerar/fechar 90 pares/180 documentos finais, 30 pares por objetivo financeiro sem reutilizar itens do piloto. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| DATA-08 | P0 | Felipe | Gustavo | DATA-07 | dupla revisão, resolução de divergências, versão/hash/manifest e separação do conjunto final. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| DATA-09 | — | Gustavo | Felipe | — | conjunto defense-aware retirado da entrega pela [DEC-058](decision-log.md#dec-058); ID e ownership preservados como trabalho futuro | CUT |
| DATA-10 | P1 | Gustavo | Felipe | RUN-08, PILOT-02 | Brutos de propostas e da coleta Odoo possuem cópias DPAPI locais completas/restauradas (DEC-091/099). Faltam fechar retenção e manifesto/pacote saneado de reprodução; não alegar cópia externa, imutável ou portátil. [Cobertura](reviews/2026-10-27-piloto-concluido.md#custódia-concluída). | ACTIVE |

## 9. Arquitetura C1 e testes de segurança

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| C1-01 | P0 | Thomaz | Felipe | SCI-01, A3A-01 | [tipos e vínculos](../gateway/src/tcc_gateway/policy_contracts.py), [schemas](../gateway/src/tcc_gateway/schemas/policy_contracts_v1.schema.json), catálogo de reason codes e [vetor de hash](../gateway/tests/fixtures/canonical_action_v1.vector.json) commitados em `ba38573`, sob [contratos fechados (DEC-036)](decision-log.md#dec-036); 269 testes offline (62 novos), documentação e segurança aprovados em 30/09. Falta revisão independente de Felipe e conferência de Thomaz; política, verificador de aprovação e execução Odoo pertencem às tarefas seguintes. Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-02 | P0 | Thomaz | Felipe | C1-01 | [política determinística](../gateway/src/tcc_gateway/policy_engine.py) e [regressões](../gateway/tests/test_policy_engine.py) commitadas em `79d36be`, sob [avaliação de regras (DEC-037)](decision-log.md#dec-037); 351 testes offline (82 novos), documentação e segurança aprovados em 30/09. Falta revisão independente de Felipe e conferência de Thomaz. Leitura Odoo, token e transação pertencem a C1-03/06/07; dependentes usam o contrato provisoriamente até o aceite. Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-03 | P0 | Thomaz | Felipe | C1-01 | [canonicalização/leitor confiável](../gateway/src/tcc_gateway/trusted_resolution.py) e regressões commitados em `4758d41`, sob [leitura independente da proposta (DEC-038)](decision-log.md#dec-038); 533 testes offline (182 novos), 17 Markdown e segurança aprovados em 30/09. Falta revisão humana independente de Felipe e conferência de Thomaz. Prova inclui JSON-2 com HTTP simulado, não integração real/ACLs; ledger, observações operacionais efetivas e revalidação transacional pertencem a C1-06/09 e ao runner; [reprodução e limites](lab-runbook.md#testes-offline-do-gateway-e-fronteira-de-leitura-c1). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-04 | P0 | Thomaz | Felipe | C1-01 | [add-on instalável sem efeitos](../odoo/addons/ap_security_executor/models/executor.py), contrato independente e [harness isolado](../scripts/test_c1_scaffold.ps1) commitados em `d2f7ad5`, sob [entrada restrita (DEC-039)](decision-log.md#dec-039); 720 testes offline e 17 no Odoo real, 17 Markdown, hashes/limpeza e segurança aprovados em 30/09. [Seleção verificada da imagem (DEC-040)](decision-log.md#dec-040) em `54564c6`, sem transferir smokes históricos. Falta apenas revisão humana independente de Felipe e conferência de Thomaz. Capacidades transacionais/assinatura/auditoria e HTTP JSON-2 pertencem às tarefas seguintes; [reprodução e limites](lab-runbook.md#instalação-e-fronteira-do-add-on-c1-04). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-05 | P0 | Thomaz | Felipe | C1-04 | [provisionamento/gate](../odoo/addons/ap_security_executor/identity.py), [inventário efetivo](../reproducibility/c1-permissions.inventory.json) e prova JSON-2 com bearer reais commitados em `3866721`, sob [identidade mínima (DEC-041)](decision-log.md#dec-041); 720 testes offline, 56 Odoo e 54 requisições HTTP aprovados, além da regressão de 17 testes sem HTTP; fonte/estado crítico inalterados, limpeza, documentação e segurança conferidos. Falta apenas revisão humana independente de Felipe e conferência de Thomaz. Sem efeitos do executor, instalação no laboratório existente ou prova de lifecycle de produção; [reprodução e limites](lab-runbook.md#identidade-restrita-e-prova-http-c1-05). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-06 | P0 | Thomaz | Felipe | C1-02, C1-04 | [núcleo privado transacional](../odoo/addons/ap_security_executor/draft_kernel.py), recibos/guardas e testes commitados em `3a9ffd6`, sob [execução transacional (DEC-042)](decision-log.md#dec-042). 815 offline, 87 Odoo (46 kernel) e regressões de 17 scaffold/56 Odoo com 54 HTTP passaram; hashes, limpeza e segurança conferidos. Falta revisão independente de Felipe e reprodução por Thomaz. `execute` público permanece fechado; aprovação, POST, auditoria, integração e concorrência entre processos continuam nos gates seguintes. [Reprodução e limites](lab-runbook.md#núcleo-transacional-privado-c1-06). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-07 | P0 | Thomaz | Felipe | C1-01 | [verificador](../odoo/addons/ap_security_executor/approval.py), [nonce transacional](../odoo/addons/ap_security_executor/approval_kernel.py) e testes commitados em `5370cc2`, sob [autenticação da aprovação (DEC-043)](decision-log.md#dec-043). 915 offline (100 novos), 115 Odoo (28 aprovação) e regressões 17/56/87 com 54 HTTP passaram; documentação, hashes, inventário, segurança e limpeza conferidos. Falta revisão de Felipe e reprodução por Thomaz. Sem POST público, custódia real, integração ou prova concorrente; [reprodução e limites](lab-runbook.md#aprovação-autenticada-e-nonce-privado-c1-07). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-08 | P0 | Thomaz | Felipe | C1-06, C1-07 | [POST privado atômico](../odoo/addons/ap_security_executor/post_kernel.py) commitado em `5582a83`, sob [contabilização aprovada (DEC-044)](decision-log.md#dec-044). 977 offline e 162 Odoo (47 POST) passaram; regressões separadas 17/56/87/115, com 54 HTTP, fonte/hashes/limpeza e segurança conferidos. Falta revisão de Felipe e reprodução por Thomaz. Público fechado; auditoria/integração e lifecycle/concorrência reais seguem pendentes. [Reprodução e limites](lab-runbook.md#contabilização-privada-aprovada-c1-08). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-09 | P0 | Thomaz | Felipe | C1-02 | [auditoria](../odoo/addons/ap_security_executor/audit_kernel.py) e [anexação direta privada](../odoo/addons/ap_security_executor/attachment_kernel.py) commitadas em `3b943c1`, sob [anexo transacional (DEC-046)](decision-log.md#dec-046). 1.148 offline (78 novos) e 246 Odoo (49 auditoria + 35 anexação), regressões 17/56/87/115/162 e 54 HTTP passaram; mesmas 32 fontes, inventário, hashes, limpeza e segurança conferidos em 04/10. PDF em DB com MIME/tamanho/SHA-256, reutilização no POST/replay e rollback integral testados. Falta revisão humana de Felipe e reprodução por Thomaz. Público fechado; workflow/runner e gates científicos separados. [Reprodução e limites](lab-runbook.md#auditoria-operacional-privada-c1-09). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-10 | P0 | Thomaz | Felipe | C1-05–09 | [bypass HTTP real](../odoo/addons/ap_security_executor/tests/test_bypass_http.py) commitado em `58d4aa7`, sob [DEC-047](decision-log.md#dec-047) e [DEC-048](decision-log.md#dec-048). 76 Odoo/20 casos novos/123 HTTP passaram em 05/10; CRUD, métodos privados/arbitrários, contexto/empresa, defaults, anexos e ledgers com alvos preenchidos e projeções idênticas. Mesmas 33 fontes das oito provas; inventário/hashes/cleanup conferidos. Falta revisão de Felipe e reprodução por Thomaz. Público fechado; repetir após integração. [Reprodução e limites](lab-runbook.md#bypass-http-c1-10). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-11 | P0 | Thomaz | Felipe | C1-06–09 | [probe de transações reais](../odoo/probes/c111_transactions.py) e correção da guarda commitados em `58d4aa7`, sob [DEC-047](decision-log.md#dec-047) e [DEC-048](decision-log.md#dec-048). 22 casos, cinco pares de conexões/bloqueios e seis retries passaram; commit/rollback/savepoint, faults, nonce, replay, deriva e lifecycle nativo conferidos. Corrida cross-PO antes `CREATED/CREATED`, agora duplicidade negada e auditada sem segundo efeito. 1.148 offline e regressões 17/56/95/123/171/255 também passaram na mesma fonte. Falta revisão de Felipe e reprodução por Thomaz. Workflow/runner e gates científicos separados. [Reprodução e limites](lab-runbook.md#transações-reais-e-ciclo-de-commit-c1-11). Revisão por agente distinto em 26/10/2026 ([relatório](reviews/2026-10-26-revisao-agente.md), [DEC-081](decision-log.md#dec-081)); assinatura humana nominal pendente. | AGENT_REVIEWED |
| C1-12 | — | Thomaz | Felipe | — | controle de saída e mensagens retirados com a avaliação de exposição de dados, conforme [retirada da exposição de dados (DEC-023)](decision-log.md#dec-023); ID preservado no histórico | CUT |
| SEC-01 | P0 | Thomaz | Felipe | C1-01 | [Matriz ameaça→controle→invariante→teste→métrica/evidência](control-test-matrix.md) concluída e revista; inclui rollback I8 e limites residuais. [parecer operacional](reviews/2026-10-26-ciencia-operacional.md). Assinatura nominal de freeze pendente. | AGENT_REVIEWED |
| SEC-02 | P1 | Thomaz | Gustavo | C1-10–11 | Inventário corrente de 366 modelos e sete críticos sem CREATE/WRITE/UNLINK; hash atual confere no lock de workflow. 21 mutações de escalada rejeitadas; add-on inalterado desde a revisão independente de bypass/transações. [parecer operacional](reviews/2026-10-26-ciencia-operacional.md) e [matriz](control-test-matrix.md). Não equivale a integração científica. | AGENT_REVIEWED |

## 10. Runner, oráculo e observabilidade experimental

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| RUN-01 | P0 | Gustavo | Felipe | SCI-03 | Registros v4 e 144 envelopes reprocessados; oráculos/IDs/hash/estado/supervisão coerentes, nenhuma ausência. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem assinatura humana ou alteração de scientific_run=false. | AGENT_REVIEWED |
| RUN-02 | P0 | Gustavo | Thomaz | RUN-01 | Integração DEC-095/096 executada e revista: 144 slots, 576 capturas, 144 restaurações, aprovação e fontes conferidas. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem nova coleta ou abertura de execute público. | AGENT_REVIEWED |
| RUN-03 | P0 | Gustavo | Felipe | estado M2 | Oráculo e bindings revistos: proposta comprometida é distinta de efeito indevido; parsing/recusa com estado legível são outcomes, aprovação exata inclui data/linhas. [Pareceres](reviews/2026-10-26-runner-analise.md). Aplicação à coleta atual segue RUN-02/09 e PILOT-03; corpus adicional foi retirado. | AGENT_REVIEWED |
| RUN-04 | P0 | Gustavo | Thomaz | RUN-02 | Mecanismo de dump/filestore e restauração por binding/projeção/IDs revisto; .4 passou com 25 capturas/16 clones e sentinelas preservadas. [parecer operacional](reviews/2026-10-26-ciencia-operacional.md). Não conclui supervisão remota, saúde/espaço/relógio ou composição: RUN-02/09; outbox desabilitada. | AGENT_REVIEWED |
| RUN-05 | P0 | Gustavo | Felipe | RUN-01–04 | Agenda integrada DEC-095 implementada: 144 slots únicos, três repetições, embaralhamento determinístico e hash da ordem. Agenda e identidades passaram na revisão offline de 27/10 (216 testes focais no total), mais contraprovas independentes de dez sementes completas e três entradas inválidas. Conferência do manifesto efetivo permanece em PILOT-03; não sortear nova ordem após resultados. | AGENT_REVIEWED |
| RUN-06 | P0 | Gustavo | Felipe | SCI-03, RUN-02 | 144 históricos com uma tentativa; 143 retornos válidos e um invalid_schema mantido como resultado avaliável, sem proposta. Regra específica DEC-096 preservada; sem misturar tentativa parcial. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). | AGENT_REVIEWED |
| RUN-07 | P1 | Gustavo | Felipe | G3-05, RUN-01 | token/custo/latência por etapa, pricing datado e request ID saneado | WAIT |
| RUN-08 | P0 | Gustavo | Thomaz | RUN-01 | Cópias locais DPAPI verificadas: 607 arquivos de propostas (DEC-091) e 20.678 arquivos do piloto Odoo (DEC-099), com restauração e originais conferidos. [Parecer/hashes](reviews/2026-10-27-piloto-concluido.md#custódia-concluída). Sem portabilidade, proteção externa ou imutabilidade; limites/retencão e export saneado seguem DATA-10/REP. | AGENT_REVIEWED |
| RUN-09 | P1 | Gustavo | Felipe | RUN-02–08 | Contrato, agenda, captura/oráculo, aprovação, supervisão, registros e reset conferidos no lote concluído. Quatro adulterações CREATE/POST rejeitadas. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md); nenhum novo ensaio auxiliar necessário. | AGENT_REVIEWED |

## 11. Piloto e congelamento

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PILOT-01 | P0 | Gustavo | Felipe | G3-05, C0-02, C0-03, C0-05, C1-11, DATA-06, RUN-09 | Configuração usada preservada e revista: coorte .4, fontes, modelo/prompt/parâmetros comuns, semente/ordem e requisições iguais entre condições. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Registros conservam marcador pré-freeze. | AGENT_REVIEWED |
| PILOT-02 | P0 | Gustavo | Thomaz | PILOT-01 | Execução fc6da3e1 concluída e revista: 144 slots íntegros, limpeza Docker conferida somente por leitura. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Custódia permanece separada em RUN-08/DATA-10; tentativa parcial fora das análises. | AGENT_REVIEWED |
| PILOT-03 | P0 | Felipe | Gustavo | PILOT-02 | [Resultado](pilot-state-resultado.md) conferido independentemente: BTSR 36/36 e 35/36, ASR-state 0/36 e UACR 0/12 por condição; ICs recomputados, 144 avaliáveis e nenhuma ausência. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem inferência de eficácia/igualdade geral. | AGENT_REVIEWED |
| PILOT-04 | P0 | Felipe | Thomaz | PILOT-03 | poder/precisão por discordância pareada; ações críticas usam 30 pares; decidir tamanho antes do conjunto final. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| PILOT-05 | P0 | Thomaz | Felipe | PILOT-03 | Revisões da execução e análise sem bloqueantes; ajustes são editoriais (limites de independência e atribuição da utilidade), tratados no resultado. Nenhuma correção de modelo, defesa, notas, parâmetros ou dados é necessária pela evidência atual. DEC-099; não ajustar ao resultado nulo. | AGENT_REVIEWED |
| PILOT-06 | P0 | Gustavo | Felipe | PILOT-05 | Não há mudança comportamental após o lote, portanto não há pares afetados que exijam reexecução. Evidência integral e tentativa parcial preservadas; revisão da coleta em DEC-099. Repetição futura somente por decisão própria, sem selecionar resultado. | AGENT_REVIEWED |
| STAT-01 | P0 | Felipe | Gustavo | RUN-01 | Componente e adaptação descritiva do analisador revistos independentemente: 34 testes, oito contraprovas e BCa/fronteira recomputados dos registros. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem testes confirmatórios; limites de amostra/completude declarados. | AGENT_REVIEWED |
| FRZ-01 | P0 | Felipe | Thomaz | SCI-01–03/05–09, PILOT-06 | Aceitar perguntas, endpoints, denominadores e análise descritiva da DEC-094. Dez pontos percentuais é referência; sem testes H1/H2/H3 ou assinatura em nome de terceiros. | WAIT |
| FRZ-02 | P0 | Felipe | Gustavo | DATA-04/06, PILOT-02 | Preservar hashes da coorte .4 de 12 pares efetivamente usada, fatos, codebook e manifestos; nenhum dataset final adicional. | WAIT |
| FRZ-03 | P0 | Gustavo | Thomaz | G3-06, C0-04, C1-11, RUN-09 | Conferir modelo/prompts/schemas/política/tentativas/timeouts/imagens, supervisão e igualdade C0/C1 na configuração efetivamente usada; competência reportada pelo piloto, sem ajuste para atingir limiar. Registro em [configuração avaliada](configuracao-avaliada.md) (29/10), lido da evidência da execução `fc6da3e1…`: os 24 documentos tiveram requisição idêntica em C0 e C1. Falta Felipe e Thomaz conferirem com as seções 3.5 e 3.8 do artigo. | AWAITING_REVIEW |
| FRZ-04 | P0 | Gustavo | Felipe | FRZ-03 | preservar artefatos OCI finais em custódia imutável ou registry aprovado; registrar digests | WAIT |
| FRZ-05 | P0 | Thomaz | Gustavo | C1-10–11 | assinar ACLs, contexto, auto-post, idempotência, concorrência, replay e fail-closed | WAIT |
| FRZ-06 | P0 | Felipe | Gustavo | SCI-03, STAT-01 | Aceitar tratamento efetivamente aplicado a falhas/ausências, paradas, reexecução e intervalos descritivos, com fronteiras explícitas e limites declarados. | WAIT |
| FRZ-07 | P0 | Gustavo | Thomaz | G3-03, FRZ-03 | comprovar secrets/egress, rotação planejada e ausência de segredo/log bruto no pacote | WAIT |
| FRZ-08 | P0 | Felipe | Thomaz/Gustavo | FRZ-01–07 | Fechar versão/tag da configuração avaliada e checklist de evidência. Pela DEC-094, não há abertura de novo corpus final ou coleta confirmatória posterior obrigatória. Tag `pilot-odoo-20261027` criada no commit de base `c6f95ec`, com checklist em [configuração avaliada](configuracao-avaliada.md); o fechamento depende de FRZ-01–07. | WAIT |

## 12. Experimentos

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| EXP-01 | P0 | Gustavo | Felipe | FRZ-08 | ensaio de um lote sem dados finais; checklist 30.2 e recuperação testados. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| EXP-02 | P0 | Gustavo | Felipe | EXP-01 | executar 1.080 runs DeepSeek C0×C1 intercaladas; raw íntegro, reset e nenhum retry pendente. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| EXP-03 | P0 | Felipe | Gustavo | EXP-02 | QA de denominadores/missing/desvios sem observar/tunar defesa durante coleta. Retirada da entrega pela [DEC-094](decision-log.md#dec-094): a avaliação é o piloto; conjunto de 90 pares é trabalho futuro | CUT |
| EXP-04 | — | Gustavo | Felipe | — | bloco defense-aware retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem execuções ou claim de robustez adaptativa | CUT |
| EXP-05 | — | Gustavo | Thomaz | — | bloco de ablação retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem atribuição causal por camada | CUT |
| EXP-06 | — | Gustavo | Felipe | — | bloco Qwen3 retirado da entrega pela [DEC-058](decision-log.md#dec-058), sem claim de generalização entre modelos | CUT |
| EXP-07 | P0 | Gustavo | Felipe | PILOT-02, RUN-08 | Fechar manifests, hashes, custo, integridade, custódia dos brutos e plano de rotação da chave da avaliação no Odoo; tentativa parcial preservada separadamente. | WAIT |

## 13. Análise e resultados

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| AN-01 | P0 | Felipe | Gustavo | PILOT-02, STAT-01 | 144 registros revalidados com agenda, IDs únicos, pares/repetições, captures, hashes, tentativas, ausência e denominadores. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Custódia completa fica RUN-08/DATA-10, sem bloquear a conferência dos números. | AGENT_REVIEWED |
| AN-02 | P0 | Felipe | Thomaz | AN-01 | ASR-proposal/state 0/36 por condição, nenhum comprometimento de proposta; contraste zero e IC conservador por 12 pares recomputados. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem redução demonstrada ou equivalência de segurança. | AGENT_REVIEWED |
| AN-03 | P0 | Felipe | Thomaz | AN-01 | BTSR C0 36/36, C1 35/36; diferença −2,7778 pp, BCa [−13,8889;0] pp, percentil de sensibilidade conferidos. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Margem 10 pp só como referência; erro de schema não é bloqueio da arquitetura. | AGENT_REVIEWED |
| AN-04 | P0 | Felipe | Gustavo | AN-01 | UACR 0/12 por condição em quatro pares A3a; contraste zero/IC conservador [−100;100] pp. C1: 47 ALLOW, 24 REVIEW_REQUIRED e um sem proposta. [Revisão do lote](reviews/2026-10-27-piloto-concluido.md). Sem bloqueios observados ou alegação causal além da evidência. | AGENT_REVIEWED |
| AN-05 | P0 | Felipe | Gustavo | AN-01 | eficiência descritiva em RQ2: latência, tokens, custo, revisão técnica potencial e variabilidade; sem teste de aceitabilidade H4 ou humana | WAIT |
| AN-06 | — | Felipe | Thomaz | — | análises defense-aware/ablação e testes de subgrupos/Holm retirados pela [DEC-058](decision-log.md#dec-058); famílias e mecanismos descritivos permanecem em AN-09 | CUT |
| AN-07 | — | Felipe | Gustavo | — | análise de transportabilidade Qwen3 retirada da entrega pela [DEC-058](decision-log.md#dec-058) | CUT |
| AN-08 | P0 | Felipe | Thomaz/Gustavo | AN-02–05 | figuras/tabelas regeneráveis, trace entre número, script, dado e commit | WAIT |
| AN-09 | P0 | Thomaz | Felipe | AN-02–05/08 | descrição por família/estratégia/template, falhas, mecanismos e limites, sem busca de significância ou causalidade por camada | WAIT |

## 14. Artigo, reprodução, submissão e defesa

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PAPER-01 | P1 | Felipe | Thomaz | SCI-07/10 | introdução e referencial com lacuna/fonte auditáveis | WAIT |
| PAPER-02 | P1 | Felipe | Gustavo | SCI-01 para rascunho; FRZ-08 para fechar | redigir metodologia em paralelo e marcar pendências; versão final reproduz exatamente protocolo/freeze e ausência de humanos Rascunho existente: incorporar a DEC-098 e corrigir os cinco pontos materiais da [revisão do artigo](reviews/2026-10-27-piloto-concluido.md#artigo-correções-materiais-ainda-necessárias), preservando o trabalho da outra sessão. | ACTIVE |
| PAPER-03 | P0 | Thomaz | Felipe | AN-09 | implementação/segurança C0/C1, sem claims além da evidência | WAIT |
| PAPER-04 | P0 | Gustavo | Felipe | EXP-07 | ambiente, dataset executado, runner, modelos, proveniência e custo operacional | WAIT |
| PAPER-05 | P0 | Felipe | Thomaz/Gustavo | AN-08/09 | resultados/discussão por RQ, números gerados, negativos e limitações Rascunho existente: incorporar a DEC-098 e corrigir os cinco pontos materiais da [revisão do artigo](reviews/2026-10-27-piloto-concluido.md#artigo-correções-materiais-ainda-necessárias), preservando o trabalho da outra sessão. DEC-098 e as cinco correções incorporadas (`c565c3d`, `8646578`, `1a339d2`); Felipe auditou em 29/10 e os ajustes foram aplicados em 31/10 ([auditoria](reviews/2026-10-29-auditoria-felipe.md)). | AWAITING_REVIEW |
| PAPER-06 | P0 | Felipe | Thomaz | PAPER-05 | Resumo/Abstract/Conclusão pós-experimento, 150–250 palavras e equivalência. Revisados por Felipe em 29/10; clareza ajustada em 31/10 (244 e 234 palavras) ([auditoria](reviews/2026-10-29-auditoria-felipe.md)); falta a conferência dele no PDF novo. | AWAITING_REVIEW |
| PAPER-07 | P0 | Felipe | Gustavo | PAPER-01–06 | reconciliar citações/referências ABNT e manter 10–20 páginas. 20/20 e 19 páginas; siglas protegidas e metadados conferidos em 31/10 na Crossref, ACL Anthology, USENIX e NeurIPS ([auditoria](reviews/2026-10-29-auditoria-felipe.md)); falta confirmar a versão da ABNT aceita pela FCI. | AWAITING_REVIEW |
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
| Plano §30.1 Freeze | SCI-01–03, DATA-04/06, C0-04/05, C1-05–11, FRZ-01–08, STAT-01; SCI-04 retirada |
| Plano §30.2 Lotes | RUN-03–09, PILOT-02, EXP-07 |
| Plano §30.3 Submissão | ADM-01–09, PAPER-06–09, SUB-01 |
| Seleção de modelos G3 | G3-01–08, C0-01–05, FRZ-03/07 |
| Institucional | ADM-01–13, PAPER-07–09, SUB-01, DEF-05/06 |
| Plano §16.3 e §17.3 (pacote de reprodução) | ADM-12, ADM-13 |
| Plano §23 (registro de uso de IA) | ADM-11 |
| Plano §16.8 (invariante de ordem do beneficiário) | SEC-A2 |
| Literatura/lacuna | SCI-05–07/10, PAPER-01 |
| Dataset e revisão | DATA-01–06/10; DATA-07/08/09 e EXP-04 retiradas |
| C1/segurança | C1-01–11, SEC-01/02; EXP-05 retirada |
| Estatística/resultados | STAT-01, PILOT-03, AN-01–09 |
| Reprodução/defesa | REP-01–03, DEF-01–06 |

## 19. Definition of Done deste backlog

O backlog é considerado operacional quando:

- toda pendência conhecida possui ID, owner, reviewer, dependência, prioridade, entregável e estado;
- os três integrantes possuem pelo menos uma tarefa `READY` sem editar o mesmo componente;
- caminho crítico e itens cortáveis estão explícitos;
- checklists do plano, seleção dos modelos e requisitos institucionais estão rastreados;
- tarefas externas distinguem resposta do usuário, consulta ao sistema e recibo; confirmação textual não é apresentada como recibo;
- mudança futura atualiza este arquivo e, se material, o decision log antes da implementação.
