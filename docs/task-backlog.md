# Backlog operacional completo do TCC II

**Decisão de ownership:** DEC-021

**Data-base:** 31/08/2026

**Estado científico:** pré-freeze; M1, M2 e G3a concluídos; nenhum resultado confirmatório coletado

## 1. Como usar este backlog

Este arquivo é a fila única de trabalho restante. Uma tarefa só muda para `DONE` quando o entregável e a Definition of Done (DoD) indicados existem e foram revisados. Percentual subjetivo, código sem teste, texto sem fonte ou execução sem manifest não concluem tarefa.

Estados permitidos:

- `READY`: pode começar sem aguardar outra tarefa;
- `ACTIVE`: possui owner trabalhando e próximo checkpoint definido;
- `WAIT`: depende de outro ID interno;
- `EXTERNAL`: depende de orientador, Oriente, credencial ou autorização do operador;
- `CONDITIONAL`: só entra se o núcleo estiver protegido em prazo/recursos;
- `DONE`: evidência aceita e commitada;
- `CUT`: removida conscientemente segundo a ordem de contingência.

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

## 3. Caminho crítico e ondas paralelas

```text
institucional + literatura/protocolo ───────────────┐
                                                    ├─→ piloto → freeze → 1.080 runs → análise → artigo
G3b egress → G3c smoke → C0 competente ────────────┤
                                                    │
dataset piloto/final + oráculo ─────────────────────┤
                                                    │
C1 + add-on + invariantes ──────────────────────────┘
```

| Onda | Janela-alvo | P1 — Felipe | P2 — Thomaz | P3 — Gustavo | Saída de sincronização |
|---|---|---|---|---|---|
| W0 | 31/08–06/09 | ADM/SPECS/LIT e schemas do dataset/piloto | contratos C0/C1, policy e plano de testes | G3b, llm-client mock, runner/oráculo v0 | contratos I1 revisados, sem chamada real |
| W1 | 07–13/09 | 24 documentos piloto + codebook + dry-run estatístico | C0 científico e núcleo C1 testados isoladamente | G3c autorizado, integração LLM/runner/Odoo | C0 competente e integração C1 pronta para E2E |
| W2 | 14–27/09 | QA do piloto/dataset e análise do piloto | add-on/ACL/approval/fault injection completos | E2E C0/C1, custódia e execução piloto | relatório do piloto e lista fechada de correções |
| W3 | 28/09–04/10 | poder/precisão, SAP e checklist de freeze | corrigir somente achados pré-declarados | fixar imagens/config/prompts e ensaio de lote | tag/manifest M6 assinados |
| W4 | 05–18/10 | QA de denominadores sem tuning | plantão de falhas, sem mudar defesa por resultado | executar 1.080 runs e preservar raw/manifest | M7 encerrado ou missing classificado |
| W5 | 19/10–02/11 | análise, figuras e edição científica | resultados de segurança/arquitetura | resultados de implementação/custo/reprodução | artigo completo aprovado internamente |
| W6 | 03–09/11 | pacote final e validação editorial | revisão final de segurança/claims | build/hash/backup/submissão e recibo | submissão inicial concluída |
| W7 | 10/11–07/12 | slides, respostas, correções e versão final | demo/arguição de segurança | demo/arguição de ambiente | banca, correção e anuência final |

Qwen3, ablação e conjunto defense-aware entram somente quando sua tarefa indicar `CONDITIONAL`; nunca deslocam as datas do núcleo DeepSeek C0×C1.

## 4. Primeiro lote de trabalho — iniciar em paralelo

Estas são as únicas frentes que devem começar imediatamente. Nenhuma depende de resultado experimental.

| Integrante | Tarefas iniciais | Não tocar ainda | Checkpoint |
|---|---|---|---|
| Felipe | ADM-01–ADM-06, SCI-01–SCI-07, DATA-01–DATA-03, STAT-01 | conjunto final de 180 documentos e thresholds pós-resultado | protocolo v0 + codebook/schema piloto + matriz de literatura |
| Thomaz | C0-01–C0-03, C1-01–C1-05, SEC-01 | conteúdo completo do conjunto final; tuning por ataque observado | contratos/policy/ACL tests isolados |
| Gustavo | ADM-07–ADM-09, G3-01–G3-04, RUN-01–RUN-04 | chave real, chamada DeepSeek e download Qwen sem gate | egress negativo + llm-client mock + runner/oráculo v0 |

## 5. Administração e requisitos institucionais

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| ADM-01 | P0 | Felipe | Gustavo | — | obter Regulamento Geral e Guia Geral vigentes; registrar origem/hash sem PII | READY |
| ADM-02 | P0 | Felipe | Thomaz | — | confirmar no Oriente extensão de arquivo, política/declaracão de IA e preservar resposta saneada | EXTERNAL |
| ADM-03 | P0 | Felipe | Gustavo | — | confirmar janela/horários/eligibilidade PPI/PPP/PPA e anomalia `31/11`; atualizar matriz | EXTERNAL |
| ADM-04 | P0 | Felipe | Gustavo | — | confirmar dados institucionais e alinhamento do tema à área/projeto do orientador | EXTERNAL |
| ADM-05 | P0 | Felipe | Thomaz | — | instituir registro semanal/quinzenal de orientação com pauta, presença, decisões e próximos passos | READY |
| ADM-06 | P0 | Felipe | Gustavo | — | coletar anuência do orientador no Oriente até 01/09 e preservar recibo fora do Git | EXTERNAL |
| ADM-07 | P0 | Gustavo | Felipe | — | verificar cadastro do grupo, três autores e recibo; não marcar concluído sem evidência | EXTERNAL |
| ADM-08 | P0 | Gustavo | Felipe | ADM-07 | protocolar requerimento no Portal até 07/09, conferir autores e preservar recibo | EXTERNAL |
| ADM-09 | P1 | Gustavo | Felipe | ADM-02 | manter calendário de submissão, avaliadores, banca, correção e anuência final | READY |
| ADM-10 | P0 | Felipe | Thomaz | DEC-021 | atualizar requisitos institucionais com papéis nominais; disponibilidade revista semanalmente | DONE |

## 6. Protocolo científico e literatura

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| SCI-01 | P0 | Felipe | Thomaz | — | criar `docs/protocol.md` com RQs, hipóteses, endpoint primário e assinaturas pré-piloto | READY |
| SCI-02 | P0 | Felipe | Gustavo | — | justificar operacionalmente a margem BTSR de 10 p.p. sem usar piloto/final | READY |
| SCI-03 | P0 | Felipe | Thomaz | — | fixar regras de retry, timeout, missing, exclusão, reexecução e nova amostra | READY |
| SCI-04 | P0 | Felipe | Gustavo | — | definir procedimento prévio de H4 para latência, custo e demanda potencial de revisão | READY |
| SCI-05 | P0 | Felipe | Thomaz | — | criar protocolo de revisão: bases, strings, inclusão/exclusão, snowballing e data de corte | READY |
| SCI-06 | P0 | Felipe | Thomaz | SCI-05 | executar busca/verificação primária e matriz comparativa de threat model, ambiente, defesa, métricas e reprodução | WAIT |
| SCI-07 | P0 | Felipe | Thomaz | SCI-06 | congelar formulação da lacuna e claims de originalidade com fontes que sustentem cada frase | WAIT |
| SCI-08 | P1 | Felipe | Gustavo | SCI-03 | registrar ética, ausência de participantes, custódia raw, retenção e revisão dupla de exports | READY |
| SCI-09 | P1 | Felipe | Thomaz | SCI-01 | mapear RQ→hipótese→endpoint→métrica→teste→figura/tabela | WAIT |
| SCI-10 | P1 | Felipe | Gustavo | SCI-05 | reconciliar bibliografia do artigo; remover fonte não citada/não verificável | WAIT |

## 7. G3, egress e baseline C0

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| G3-01 | P0 | Gustavo | Thomaz | DEC-020, G3a | criar processo/serviço `llm-client` sem credencial Odoo e API interna tipada | READY |
| G3-02 | P0 | Gustavo | Thomaz | G3-01 | materializar redes separadas e proxy TLS pass-through com allowlist `api.deepseek.com:443` | WAIT |
| G3-03 | P0 | Gustavo | Thomaz | G3-02 | testes negativos: gateway/Odoo/db sem Internet; cliente sem ERP/Internet direta; proxy nega host/IP/porta alternativos | WAIT |
| G3-04 | P0 | Gustavo | Felipe | G3-01 | harness de smoke sintético, manifest saneado e varredura de logs, ainda com transporte mock | READY |
| G3-05 | P0 | Gustavo | Thomaz | G3-03, G3-04, autorização | uma chamada DeepSeek sintética mínima; registrar alias/ID/uso/latência/hashes sem segredo/raw no Git | EXTERNAL |
| G3-06 | P1 | Gustavo | Felipe | G3-05 | observar defaults/limites, propor timeout/backoff/max tokens e fechar parâmetros candidatos do piloto | WAIT |
| G3-07 | P2 | Gustavo | Thomaz | núcleo protegido, autorização | baixar Qwen3, registrar manifest/blobs/Ollama/Modelfile sem expor dados | CONDITIONAL |
| G3-08 | P2 | Gustavo | Felipe | G3-07 | smoke Qwen: offload, CPU/GPU/RAM/VRAM, TTFT, tok/s, latência, contexto e OOM | CONDITIONAL |
| C0-01 | P0 | Thomaz | Felipe | SCI-01, G3a | especificar prompt-base, ações e ferramentas plausíveis comuns; separar construção C0/C1 do transporte | READY |
| C0-02 | P0 | Thomaz | Gustavo | C0-01 | integrar adapter LLM ao fluxo direto C0 sem policy C1; valores tipados chegam ao executor | WAIT |
| C0-03 | P0 | Thomaz | Gustavo | C0-01 | definir capacidades mínimas: rascunho, ação crítica simulada/outbox e mensagem local, sem pagamento/e-mail real | READY |
| C0-04 | P0 | Thomaz | Felipe | C0-02, DATA-05, G3-05 | medir competência benigna no piloto e corrigir apenas falhas funcionais pré-freeze | WAIT |
| C0-05 | P0 | Felipe | Gustavo | C0-04 | revisão independente de plausibilidade; documentar diferenças não relacionadas à segurança | WAIT |

## 8. Dataset, ground truth e red team

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| DATA-01 | P0 | Felipe | Gustavo | contrato atual | schemas de `pair_id`, `scenario_id`, fatos, ação esperada, deltas proibidos e labels | READY |
| DATA-02 | P0 | Felipe | Thomaz | threat model | codebook de famílias, posições, estratégias, sucesso e falhas; sem revelar conjunto final a P2 | READY |
| DATA-03 | P0 | Felipe | Gustavo | DATA-01 | gerador/template de PDF sintético com watermark, hashes e validação de texto extraído | READY |
| DATA-04 | P0 | Felipe | Gustavo | DATA-01–03 | 12 pares/24 documentos do piloto, fora do conjunto final, com ground truth preliminar | WAIT |
| DATA-05 | P0 | Gustavo | Felipe | DATA-04, G3-04 | validar Delivery Rate: payload chega intacto ao modelo; registrar texto/hash/posição | WAIT |
| DATA-06 | P0 | Gustavo | Felipe | DATA-04 | revisão independente dos fatos Odoo, ações esperadas, deltas, fixtures e oráculo | WAIT |
| DATA-07 | P0 | Felipe | Gustavo | PILOT-04 | gerar/fechar 90 pares/180 documentos finais sem reutilizar itens do piloto | WAIT |
| DATA-08 | P0 | Felipe | Gustavo | DATA-07 | dupla revisão, resolução de divergências, versão/hash/manifest e separação do conjunto final | WAIT |
| DATA-09 | P1 | Felipe | Thomaz | DATA-02 | conjunto defense-aware com orçamento pré-fixado, sem substituir o principal | WAIT |
| DATA-10 | P1 | Gustavo | Felipe | DATA-08 | custódia externa criptografada, cópia imutável, retenção e manifest SHA-256 saneado | WAIT |

## 9. Arquitetura C1 e testes de segurança

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| C1-01 | P0 | Thomaz | Felipe | SCI-01, proposta v1 | contratos `PolicyInput`, `PolicyDecision`, reason codes e capability request, schemas fechados | READY |
| C1-02 | P0 | Thomaz | Felipe | C1-01 | policy engine puro para PO/fornecedor/moeda/valor/beneficiário/duplicidade/fase/fail-closed | WAIT |
| C1-03 | P0 | Thomaz | Gustavo | C1-01 | canonicalização e resolução por chaves confiáveis, nunca IDs do documento | READY |
| C1-04 | P0 | Thomaz | Gustavo | C1-01 | scaffold `ap_security_executor`, modelo de serviço e único método `execute(command)` | READY |
| C1-05 | P0 | Thomaz | Gustavo | C1-04 | grupo/ACL mínimos; usuário sem grupos de faturamento/compras/pagamento; inventário de leituras residuais | WAIT |
| C1-06 | P0 | Thomaz | Gustavo | C1-02, C1-04 | revalidação transacional, locks de PO/idempotência, unicidade e criação de rascunho confiável | WAIT |
| C1-07 | P0 | Thomaz | Felipe | C1-01 | autorização vinculada a hash/ação/fornecedor/valor/moeda/banco/expiração/nonce | WAIT |
| C1-08 | P0 | Thomaz | Gustavo | C1-06, C1-07 | modos `CREATE_DRAFT` e `POST_APPROVED`; solicitação de pagamento somente no outbox | WAIT |
| C1-09 | P0 | Thomaz | Felipe | C1-02 | auditoria com proveniência, regras, identidade, before/after, recibo idempotente e falha segura | WAIT |
| C1-10 | P0 | Thomaz | Gustavo | C1-05–09 | testes diretos de bypass JSON-2, CRUD genérico, método arbitrário, contexto hostil e troca de empresa | WAIT |
| C1-11 | P0 | Thomaz | Gustavo | C1-06–09 | concorrência, replay, alteração pós-aprovação, duplicidade e fault injection sem mutação residual | WAIT |
| C1-12 | P1 | Thomaz | Felipe | C1-09 | controle de saída/canário no outbox e mensagens locais allowlisted | WAIT |
| SEC-01 | P0 | Thomaz | Felipe | C1-01 | matriz threat→controle→invariante→teste→evidência, incluindo limites residuais | READY |
| SEC-02 | P1 | Thomaz | Gustavo | C1-10–12 | inventário de permissões/capacidades e prova de zero mutação crítica fora do método | WAIT |

## 10. Runner, oráculo e observabilidade experimental

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| RUN-01 | P0 | Gustavo | Felipe | SCI-03 | schema `RunRecord` com configuração, hashes, condição, modelo, tentativas, estado e outcomes | READY |
| RUN-02 | P0 | Gustavo | Thomaz | RUN-01 | runner único C0/C1, sem lógica de defesa, com relógios e tentativas individualizadas | READY |
| RUN-03 | P0 | Gustavo | Felipe | estado M2 | oráculo de proposta/policy/ação/estado, canário, invariantes e reason codes | READY |
| RUN-04 | P0 | Gustavo | Thomaz | RUN-02 | reset/asserts de fixture, outbox vazio, saúde, espaço, relógio e estado residual | READY |
| RUN-05 | P0 | Gustavo | Felipe | RUN-01–04 | pareamento, ordem intercalada/randomizada, três repetições e seed/ordem registradas | WAIT |
| RUN-06 | P0 | Gustavo | Felipe | SCI-03, RUN-02 | retry/missing idênticos em C0/C1; falhas de parsing/recusa permanecem outcomes | WAIT |
| RUN-07 | P1 | Gustavo | Felipe | G3-05, RUN-01 | token/custo/latência por etapa, pricing datado e request ID saneado | WAIT |
| RUN-08 | P0 | Gustavo | Thomaz | RUN-01 | writer raw fora do Git, manifest de hashes e política de retenção/backup imutável | READY |
| RUN-09 | P1 | Gustavo | Felipe | RUN-02–08 | ensaio sintético completo sem conjunto final; valida schemas e gera dados para dry-run estatístico | WAIT |

## 11. Piloto e congelamento

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PILOT-01 | P0 | Gustavo | Felipe | G3-05, C0-04, C1-11, DATA-06, RUN-09 | checklist de prontidão: 24 docs × C0/C1 × 3 = 144 runs, sem conjunto final | WAIT |
| PILOT-02 | P0 | Gustavo | Thomaz | PILOT-01 | executar piloto, preservar raw/manifest e restaurar estado a cada cenário | WAIT |
| PILOT-03 | P0 | Felipe | Gustavo | PILOT-02 | relatório de competência, ASR diagnóstica, BTSR, Delivery, latência, custo, erros e denominadores | WAIT |
| PILOT-04 | P0 | Felipe | Thomaz | PILOT-03 | poder/precisão por discordância pareada; decidir tamanho antes do conjunto final | WAIT |
| PILOT-05 | P0 | Thomaz | Felipe | PILOT-03 | lista fechada de correções funcionais/segurança; nenhuma escolha pelo melhor resultado final | WAIT |
| PILOT-06 | P0 | Gustavo | Felipe | PILOT-05 | reexecutar integralmente piloto afetado e produzir relatório final de prontidão | WAIT |
| STAT-01 | P0 | Felipe | Gustavo | RUN-01 | pipeline estatístico em dados sintéticos: denominadores, McNemar, IC, bootstrap por par, GEE/misto | READY |
| FRZ-01 | P0 | Felipe | Thomaz | SCI-01–09, PILOT-06 | assinar RQs, hipóteses, endpoints, métricas, margem, H4 e SAP | WAIT |
| FRZ-02 | P0 | Felipe | Gustavo | DATA-08 | congelar dataset/ground truth/codebook/manifests por hash | WAIT |
| FRZ-03 | P0 | Gustavo | Thomaz | G3-06, C1-11, RUN-09 | congelar modelos/prompts/schemas/policy/retry/timeouts/imagens/configuração e igualdade C0/C1 | WAIT |
| FRZ-04 | P0 | Gustavo | Felipe | FRZ-03 | preservar artefatos OCI finais em custódia imutável ou registry aprovado; registrar digests | WAIT |
| FRZ-05 | P0 | Thomaz | Gustavo | C1-10–12 | assinar ACLs, contexto, auto-post, idempotência, concorrência, replay e fail-closed | WAIT |
| FRZ-06 | P0 | Felipe | Gustavo | SCI-03, STAT-01 | assinar missing/exclusão/desvio/reexecução/defense-aware e plano de análise | WAIT |
| FRZ-07 | P0 | Gustavo | Thomaz | G3-03, FRZ-03 | comprovar secrets/egress, rotação planejada e ausência de segredo/log bruto no pacote | WAIT |
| FRZ-08 | P0 | Felipe | Thomaz/Gustavo | FRZ-01–07 | release/tag 1.3 e checklist M6 completos antes de abrir o conjunto final | WAIT |

## 12. Experimentos

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| EXP-01 | P0 | Gustavo | Felipe | FRZ-08 | ensaio de um lote sem dados finais; checklist 30.2 e recuperação testados | WAIT |
| EXP-02 | P0 | Gustavo | Felipe | EXP-01 | executar 1.080 runs DeepSeek C0×C1 intercaladas; raw íntegro, reset e nenhum retry pendente | WAIT |
| EXP-03 | P0 | Felipe | Gustavo | EXP-02 | QA de denominadores/missing/desvios sem observar/tunar defesa durante coleta | WAIT |
| EXP-04 | P1 | Gustavo | Felipe | EXP-02, DATA-09 | 216 runs defense-aware conforme orçamento congelado | CONDITIONAL |
| EXP-05 | P1 | Gustavo | Thomaz | EXP-02 | 576 runs de ablação leave-one-out conforme matriz congelada | CONDITIONAL |
| EXP-06 | P2 | Gustavo | Felipe | G3-08, EXP-02 | 432 runs Qwen3 C0×C1 em amostra de 72 documentos | CONDITIONAL |
| EXP-07 | P0 | Gustavo | Felipe | EXP-02–06 | fechar manifests, hashes, custo, integridade, custódia raw e rotação da chave | WAIT |

## 13. Análise e resultados

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| AN-01 | P0 | Felipe | Gustavo | EXP-07, STAT-01 | validar dados, schema, duplicatas, pares, missing, retries e denominadores | WAIT |
| AN-02 | P0 | Felipe | Thomaz | AN-01 | H1: ASR-proposal/policy/state com efeito pareado, IC95% e teste pré-definido | WAIT |
| AN-03 | P0 | Felipe | Thomaz | AN-01 | H3: BTSR e não inferioridade com limite `−0,10` e IC95% | WAIT |
| AN-04 | P0 | Felipe | Gustavo | AN-01 | H2/utilidade: UACR, SDR, FBR, escalation e análise de falhas | WAIT |
| AN-05 | P0 | Felipe | Gustavo | AN-01 | H4/overhead: latência, tokens, custo, revisão potencial e limites congelados | WAIT |
| AN-06 | P1 | Felipe | Thomaz | EXP-04/05 | defense-aware, ablação, subgrupos/Holm e rotulagem exploratória | CONDITIONAL |
| AN-07 | P2 | Felipe | Gustavo | EXP-06 | transportabilidade DeepSeek/Qwen sem comparação causal entre modelos | CONDITIONAL |
| AN-08 | P0 | Felipe | Thomaz/Gustavo | AN-02–07 | figuras/tabelas regeneráveis, trace entre número, script, dado e commit | WAIT |
| AN-09 | P0 | Thomaz | Felipe | AN-02–08 | análise qualitativa das falhas, mecanismos e limites dos controles | WAIT |

## 14. Artigo, reprodução, submissão e defesa

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PAPER-01 | P1 | Felipe | Thomaz | SCI-07/10 | introdução e referencial com lacuna/fonte auditáveis | WAIT |
| PAPER-02 | P1 | Felipe | Gustavo | FRZ-08 | metodologia final reproduz exatamente protocolo/freeze e ausência de humanos | WAIT |
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

## 15. Itens condicionados e explicitamente fora do caminho crítico

| Item | Classe | Regra |
|---|---|---|
| Qwen3 14B | P2 condicionado | cortar antes de reduzir/atrasar DeepSeek principal, dataset, C1, piloto, análise ou artigo |
| Defense-aware e ablação | P1 condicionado | executar somente após principal íntegro e conforme orçamento congelado |
| UI de revisão | P3 opcional | não implementar antes de experimento; logs/tabelas bastam |
| Detector de prompt injection | P3 opcional | não integra núcleo; se existir, nunca autoriza e precisa bloco exploratório |
| Presidio | P3 opcional | apenas privacidade; não vender como defesa contra injection |
| OCR, NF-e válida, SaaS 19.4, Enterprise, IA nativa, pagamento/e-mail real | fora do escopo | não criar tarefa nem protótipo durante o TCC |
| Segundo domínio/ERP/idioma | trabalho futuro | não entra no cronograma atual |

## 16. Contratos de integração I1

Antes de integrar as três trilhas, os seguintes contratos devem estar versionados e revisados:

1. `vendor-bill-model-output/v1` e `vendor-bill-proposal/v1` — já existentes;
2. `dataset-manifest/v1`, `pair/scenario ground-truth/v1` — P1, revisão P3/P2 apenas de schema;
3. `policy-input/v1`, `policy-decision/v1`, reason codes e capability command — P2, revisão P1/P3;
4. `run-record/v1` e oracle outcome — P3, revisão P1/P2;
5. prompt envelope C0/C1 e hashes — P2, revisão P1;
6. reset/fixture manifest — P3, revisão P2;
7. SAP e mapping RQ→endpoint — P1, revisão P2/P3.

Nenhuma integração deve contornar um contrato com dicionário livre, ID interno fornecido pelo documento, RPC genérico ou campo `context` externo.

## 17. Regras de merge e revisão

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
| Plano §30.1 Freeze | SCI-01–04, DATA-07/08, C0-04/05, C1-05–11, FRZ-01–08, STAT-01 |
| Plano §30.2 Lotes | RUN-03–08, EXP-01/02 |
| Plano §30.3 Submissão | ADM-01–09, PAPER-06–09, SUB-01 |
| Seleção de modelos G3 | G3-01–08, C0-01–05, FRZ-03/07 |
| Institucional | ADM-01–10, PAPER-07–09, SUB-01, DEF-05/06 |
| Literatura/lacuna | SCI-05–07/10, PAPER-01 |
| Dataset e red team | DATA-01–10, EXP-04 |
| C1/segurança | C1-01–12, SEC-01/02, EXP-05 |
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
