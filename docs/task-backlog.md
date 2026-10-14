# Backlog operacional completo do TCC II

**Decisão de ownership:** [divisão do trabalho (DEC-021)](decision-log.md#dec-021)

**Data-base:** 13/10/2026

**Estado científico:** pré-congelamento. As [observações reais ligadas à ação (DEC-053)](lab-runbook.md#observacoes-operacionais-ligadas-a-acao) passaram: 1.735 offline, 408 Odoo, oito casos normais/nove observações aceitas pelo contrato gateway e regressão C1-11 de 22 casos. CREATE/POST e provas anteriores mantêm seus próprios hashes. Isso comprova engenharia, não resistência do LLM a ataques nem integração experimental completa. Próximo: ligar o caminho observado à política/execução nativas; depois captura/reset/oráculo. RUN-02/03 seguem `ACTIVE`; `execute` permanece fechado; revisão humana, competência C0 no piloto, dataset, freeze e resultados confirmatórios pendentes. Escopo conforme [DEC-023](decision-log.md#dec-023); alias em [DEC-024](decision-log.md#dec-024).

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
| SCI-01 | P0 | Felipe | Thomaz | — | [protocolo candidato pré-piloto (DEC-032)](decision-log.md#dec-032) commitado em `d0f11d6`, com RQs, hipóteses, endpoint primário e validação Markdown; falta revisão independente/assinatura, conforme [DEC-034](decision-log.md#dec-034) | AWAITING_REVIEW |
| SCI-02 | P0 | Felipe | Gustavo | — | justificar operacionalmente a margem BTSR de 10 p.p. sem usar piloto/final | READY |
| SCI-03 | P0 | Felipe | Thomaz | — | [regras candidatas e classificador puro (DEC-032)](decision-log.md#dec-032) testados offline; faltam parâmetros de retry da observação Odoo, integração, revisão independente e assinatura antes do freeze | ACTIVE |
| SCI-04 | P0 | Felipe | Gustavo | — | definir procedimento prévio de [limites de custo operacional (H4)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h4) para latência, custo e demanda potencial de revisão | READY |
| SCI-05 | P0 | Felipe | Thomaz | — | criar protocolo de revisão: bases, strings, inclusão/exclusão, snowballing e data de corte | READY |
| SCI-06 | P0 | Felipe | Thomaz | SCI-05 | executar busca/verificação primária e matriz comparativa de threat model, ambiente, defesa, métricas e reprodução | WAIT |
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
| G3-07 | P2 | Gustavo | Thomaz | núcleo protegido, autorização | baixar Qwen3, registrar manifest/blobs/Ollama/Modelfile sem expor dados | CONDITIONAL |
| G3-08 | P2 | Gustavo | Felipe | G3-07 | smoke Qwen: offload, CPU/GPU/RAM/VRAM, TTFT, tok/s, latência, contexto e OOM | CONDITIONAL |
| A3A-01 | P0 | Gustavo | Thomaz e Felipe | [contrato de ação v2 (DEC-035)](decision-log.md#dec-035) | schemas, adapters e [transporte/consumidores v2 (DEC-050)](decision-log.md#dec-050) preservados. [Prova nativa (DEC-051)](decision-log.md#dec-051) confirma POST C0 sem aprovação no alvo confiável, sem reescrever campos propostos. Faltam revisão independente e aceite da semântica A3a; não é taxa de ataques | AWAITING_REVIEW |
| C0-01 | P0 | Thomaz | Felipe | SCI-01, G3a | especificar prompt-base, ações e ferramentas plausíveis comuns; separar construção C0/C1 do transporte | READY |
| C0-02 | P0 | Thomaz | Gustavo | C0-01, A3A-01 | consumidor v2, ponte e [sete casos nativos (DEC-051)](decision-log.md#dec-051) passaram com identidade funcional não administrativa: CREATE benigno/desvio de valor/beneficiário, POST sem aprovação, alvo ausente/ambíguo e erro nativo. Argumentos, alvo e efeitos conferidos pós-commit. Ainda faltam integração experimental completa, revisão e competência benigna no piloto | ACTIVE |
| C0-03 | P0 | Thomaz | Gustavo | C0-01 | definir capacidades mínimas: rascunho e contabilização autorizada; solicitação simulada de pagamento continua extensão secundária, sem pagamento/e-mail real | READY |
| C0-04 | P0 | Thomaz | Felipe | C0-02, DATA-05, G3-05 | medir competência benigna no piloto e corrigir apenas falhas funcionais pré-freeze | WAIT |
| C0-05 | P0 | Felipe | Gustavo | C0-04 | revisão independente de plausibilidade; documentar diferenças não relacionadas à segurança | WAIT |

## 8. Dataset, ground truth e red team

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| DATA-01 | P0 | Felipe | Gustavo | contrato atual | schemas de `pair_id`, `scenario_id`, fatos, ação esperada, deltas proibidos e labels | READY |
| DATA-02 | P0 | Felipe | Thomaz | threat model | codebook de famílias, posições, estratégias, sucesso e falhas; sem revelar conjunto final a P2 | READY |
| DATA-03 | P0 | Felipe | Gustavo | DATA-01 | gerador/template de PDF sintético com watermark, hashes e validação de texto extraído | READY |
| DATA-04 | P0 | Felipe | Gustavo | DATA-01–03 | 12 pares/24 documentos do piloto, quatro pares por objetivo financeiro, fora do conjunto final, com ground truth preliminar | WAIT |
| DATA-05 | P0 | Gustavo | Felipe | DATA-04, G3-04 | validar Delivery Rate: payload chega intacto ao modelo; registrar texto/hash/posição | WAIT |
| DATA-06 | P0 | Gustavo | Felipe | DATA-04 | revisão independente dos fatos Odoo, ações esperadas, deltas, fixtures e oráculo | WAIT |
| DATA-07 | P0 | Felipe | Gustavo | PILOT-04 | gerar/fechar 90 pares/180 documentos finais, 30 pares por objetivo financeiro sem reutilizar itens do piloto | WAIT |
| DATA-08 | P0 | Felipe | Gustavo | DATA-07 | dupla revisão, resolução de divergências, versão/hash/manifest e separação do conjunto final | WAIT |
| DATA-09 | P1 | Gustavo | Felipe | DATA-02 | conjunto defense-aware com orçamento pré-fixado, sem substituir o principal; owner P3 conduz o red team e P1 aceita, conforme a RACI de §19.2 do plano | WAIT |
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
| RUN-01 | P0 | Gustavo | Felipe | SCI-03 | schema `RunRecord` com configuração, hashes, condição, modelo, tentativas, estado e outcomes; classificador técnico pré-freeze existe, mas SCI-03 não está assinado | WAIT |
| RUN-02 | P0 | Gustavo | Thomaz | RUN-01 | estágio LLM/v2, registro, CREATE/POST privados e [observações reais candidate-bound (DEC-053)](decision-log.md#dec-053) implementados. 408 Odoo, oito casos/nove envelopes com contrato gateway passaram; 190 testes gateway cobrem novo caminho observado e CREATE só após ALLOW. Não é round-trip nativo completo de leitura/política/execução. Próximo: ligar esse caminho ao runner real; depois RUN-01/captura/reset/supervisão/RunRecord. [Reprodução e limites](lab-runbook.md#observacoes-operacionais-ligadas-a-acao) | ACTIVE |
| RUN-03 | P0 | Gustavo | Felipe | estado M2 | núcleo/conversor v2 preservados; [prova nativa (DEC-051)](decision-log.md#dec-051) observa empresa sem filtro pela proposta e confere efeitos C0 e recibo/evento/anexo C1 em cursor novo. É projeção mínima, não captura completa de §14.5 nem classificação científica por evaluate_oracle. Faltam coletor/reset, atribuição no runner completo, contratos DATA-02, teste integrado e revisão de Felipe | ACTIVE |
| RUN-04 | P0 | Gustavo | Thomaz | RUN-02 | reset/asserts de fixture, saúde, espaço, relógio e estado residual; verificar outbox vazio se a extensão secundária existir | READY |
| RUN-05 | P0 | Gustavo | Felipe | RUN-01–04 | pareamento, ordem intercalada/randomizada, três repetições e seed/ordem registradas | WAIT |
| RUN-06 | P0 | Gustavo | Felipe | SCI-03, RUN-02 | retry/missing idênticos em C0/C1; [política técnica de tentativas (DEC-031)](decision-log.md#dec-031) testada offline, mas regra científica de `missing` e validação integrada pendentes; falhas de parsing/recusa permanecem outcomes | WAIT |
| RUN-07 | P1 | Gustavo | Felipe | G3-05, RUN-01 | token/custo/latência por etapa, pricing datado e request ID saneado | WAIT |
| RUN-08 | P0 | Gustavo | Thomaz | RUN-01 | writer raw fora do Git, manifest de hashes e política de retenção/backup imutável | READY |
| RUN-09 | P1 | Gustavo | Felipe | RUN-02–08 | ensaio sintético completo sem conjunto final; valida schemas e gera dados para dry-run estatístico | WAIT |

## 11. Piloto e congelamento

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| PILOT-01 | P0 | Gustavo | Felipe | G3-05, C0-04, C1-11, DATA-06, RUN-09 | checklist de prontidão: 24 docs × C0/C1 × 3 = 144 runs, sem conjunto final | WAIT |
| PILOT-02 | P0 | Gustavo | Thomaz | PILOT-01 | executar piloto, preservar raw/manifest e restaurar estado a cada cenário | WAIT |
| PILOT-03 | P0 | Felipe | Gustavo | PILOT-02 | relatório de competência, ASR diagnóstica, BTSR, Delivery, latência, custo, erros e denominadores | WAIT |
| PILOT-04 | P0 | Felipe | Thomaz | PILOT-03 | poder/precisão por discordância pareada; ações críticas usam 30 pares; decidir tamanho antes do conjunto final | WAIT |
| PILOT-05 | P0 | Thomaz | Felipe | PILOT-03 | lista fechada de correções funcionais/segurança; nenhuma escolha pelo melhor resultado final | WAIT |
| PILOT-06 | P0 | Gustavo | Felipe | PILOT-05 | reexecutar integralmente piloto afetado e produzir relatório final de prontidão | WAIT |
| STAT-01 | P0 | Felipe | Gustavo | RUN-01 | pipeline estatístico em dados sintéticos: denominadores, McNemar, IC, bootstrap por par, GEE/misto | READY |
| FRZ-01 | P0 | Felipe | Thomaz | SCI-01–09, PILOT-06 | assinar RQs, hipóteses, endpoints, métricas, margem, [limites de custo operacional (H4)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h4) e SAP | WAIT |
| FRZ-02 | P0 | Felipe | Gustavo | DATA-08 | congelar dataset/ground truth/codebook/manifests por hash | WAIT |
| FRZ-03 | P0 | Gustavo | Thomaz | G3-06, C1-11, RUN-09 | congelar modelos/prompts/schemas/policy/retry/timeouts/imagens/configuração e igualdade C0/C1 | WAIT |
| FRZ-04 | P0 | Gustavo | Felipe | FRZ-03 | preservar artefatos OCI finais em custódia imutável ou registry aprovado; registrar digests | WAIT |
| FRZ-05 | P0 | Thomaz | Gustavo | C1-10–11 | assinar ACLs, contexto, auto-post, idempotência, concorrência, replay e fail-closed | WAIT |
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
| EXP-05 | P1 | Gustavo | Thomaz | EXP-02 | 576 execuções de ablação: 48 documentos × quatro condições × três repetições; 12 benignos e 12 ataques por objetivo | CONDITIONAL |
| EXP-06 | P2 | Gustavo | Felipe | G3-08, EXP-02 | 432 runs Qwen3 C0×C1 em amostra de 72 documentos | CONDITIONAL |
| EXP-07 | P0 | Gustavo | Felipe | EXP-02; EXP-04–06 somente se executadas | fechar manifests, hashes, custo, integridade, custódia raw e rotação da chave | WAIT |

## 13. Análise e resultados

| ID | P | Owner | Reviewer | Dep. | Entregável e DoD | Estado |
|---|---:|---|---|---|---|---|
| AN-01 | P0 | Felipe | Gustavo | EXP-07, STAT-01 | validar dados, schema, duplicatas, pares, missing, retries e denominadores | WAIT |
| AN-02 | P0 | Felipe | Thomaz | AN-01 | [redução do sucesso dos ataques (H1)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h1): ASR-proposal/policy/state com efeito pareado, IC95% e teste pré-definido | WAIT |
| AN-03 | P0 | Felipe | Thomaz | AN-01 | [preservação da utilidade (H3)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h3): BTSR e não inferioridade com limite `−0,10` e IC95% | WAIT |
| AN-04 | P0 | Felipe | Gustavo | AN-01 | [redução de ações críticas indevidas (H2)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h2) e utilidade: UACR, falsos bloqueios, encaminhamentos e análise de falhas | WAIT |
| AN-05 | P0 | Felipe | Gustavo | AN-01 | [limites de custo operacional (H4)](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#h4): latência, tokens, custo, revisão potencial e limites congelados | WAIT |
| AN-06 | P1 | Felipe | Thomaz | EXP-04/05 | defense-aware, ablação, subgrupos/Holm e rotulagem exploratória | CONDITIONAL |
| AN-07 | P2 | Felipe | Gustavo | EXP-06 | transportabilidade DeepSeek/Qwen sem comparação causal entre modelos | CONDITIONAL |
| AN-08 | P0 | Felipe | Thomaz/Gustavo | AN-02–05; AN-06–07 somente se executadas | figuras/tabelas regeneráveis, trace entre número, script, dado e commit | WAIT |
| AN-09 | P0 | Thomaz | Felipe | AN-02–05/08; AN-06–07 somente se executadas | análise qualitativa das falhas, mecanismos e limites dos controles | WAIT |

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
| Plano §30.1 Freeze | SCI-01–04, DATA-07/08, C0-04/05, C1-05–11, FRZ-01–08, STAT-01 |
| Plano §30.2 Lotes | RUN-03–08, EXP-01/02 |
| Plano §30.3 Submissão | ADM-01–09, PAPER-06–09, SUB-01 |
| Seleção de modelos G3 | G3-01–08, C0-01–05, FRZ-03/07 |
| Institucional | ADM-01–13, PAPER-07–09, SUB-01, DEF-05/06 |
| Plano §16.3 e §17.3 (pacote de reprodução) | ADM-12, ADM-13 |
| Plano §23 (registro de uso de IA) | ADM-11 |
| Plano §16.8 (invariante de ordem do beneficiário) | SEC-A2 |
| Literatura/lacuna | SCI-05–07/10, PAPER-01 |
| Dataset e red team | DATA-01–10, EXP-04 |
| C1/segurança | C1-01–11, SEC-01/02, EXP-05 |
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
