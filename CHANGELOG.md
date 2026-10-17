# Changelog do plano-mestre

Este arquivo registra versões publicadas do plano. Cada versão, a partir de 1.2, deve corresponder a um commit Git dedicado contendo a fonte normativa, decisões, changelog e manifesto aplicáveis.

## [1.2.19] — 2026-10-17

- aplicado o [corte da entrega (DEC-058)](docs/decision-log.md#dec-058): preservados 90 pares/180 documentos, três repetições, 1.080 execuções principais e piloto separado de 144; total obrigatório de 1.224;
- Qwen3, ablação e ataques adaptados à defesa passam a trabalho futuro; RQ4/H5 ficam reservados e H4 passa a descritivo, sem alegação de aceitabilidade;
- mantidos H1 → H3 → H2, pareamento, bootstrap por par, margem de utilidade de −0,10, tratamento de missing e gate pré-freeze para implementação/revisão das regras de fronteira;
- revisão de literatura dirigida e transparente; análises secundárias descritivas; protocolo, backlog de três trilhas, artigo e cronograma atualizados sem relaxar a fronteira do executor C1;
- evidências técnicas anteriores permanecem distintas de revisão humana, piloto, freeze e resultado científico. Esta release não faz chamada à API nem altera a defesa.

## [1.2.18] — 2026-09-30

- a [execução transacional privada (DEC-042)](docs/decision-log.md#dec-042) esclarece a identidade documental por digest e IDs confiáveis, sem referência externa; unicidade é por modo, e retry preserva o comando inteiro;
- separados campos propostos e valores internos fixos necessários para impedir defaults pessoais críticos; o contrato recebido continua fechado;
- entrada pública permanece bloqueada até os controles de autorização, aprovação e auditoria; esta release não contém o código C1-06 nem altera amostra, hipótese, métrica ou margem.

## [1.2.17] — 2026-09-26

- criada a [regra de aceite intermediário (DEC-034)](docs/decision-log.md#dec-034): `AWAITING_REVIEW` identifica implementação completa aguardando revisão independente; desenvolvimento dependente pode avançar com contrato versionado, mas piloto e freeze exigem aceite `DONE`;
- a [correção do contrato A3a (DEC-035)](docs/decision-log.md#dec-035) preserva os schemas v1 históricos de M2/G3c e especifica `vendor-bill-action-output/v2`/`vendor-bill-action-proposal/v2` para que a ação crítica seja proposta pelo modelo em ambos C0/C1;
- atualizados o exemplo de `ProposedAction`, a pré-imagem `CanonicalAction.action_schema_version` e a matriz A3a para separar dados não confiáveis, alvo resolvido em estado confiável e autorização vinculada;
- esta release documenta o contrato antes do código. Implementação, integração, revisão, piloto e freeze permanecem pendentes; hipóteses, margem e tamanhos amostrais não mudam.

## [1.2.16] — 2026-09-26

- executado o [smoke canônico G3-06 (DEC-030)](docs/decision-log.md#dec-030) em uma chamada real sintética, sem retry: `deepseek-flash` solicitado/retornado, proposta tipada, um túnel permitido e manifesto saneado com SHA-256 `45f7722115020ec445ef89cf0cde2d7e96448315bdb9d595ddabc01caa6af5be`;
- preservado o smoke G3c com alias legado, marcador e manifesto distintos; nenhum request/response bruto ou segredo entrou no Git;
- validados 138 testes offline do gateway/cliente, 6 do proxy, topologia G3c/G3-06, sintaxe PowerShell, Markdown e segurança do repositório;
- mantidos `G3-06` e `RUN-03` ativos: prazos de parede/retries no runner, integração Odoo, competência C0, revisão independente, piloto e freeze não foram comprovados.

## [1.2.15] — 2026-09-26

- ratificado o [pacote técnico pré-piloto (DEC-029)](docs/decision-log.md#dec-029): alias solicitado `deepseek-flash`, *thinking* desligado, temperatura zero, JSON object, 2.048 tokens, conexão de **10 s** e inatividade de leitura de 120 s;
- separados os limites aprovados ainda não implementados: 180 s de parede por tentativa, 300 s por chamada lógica e até duas novas tentativas com esperas 2 s/4 s, somente para timeout/conexão e HTTP 408/429/5xx;
- preservado o smoke G3c com alias legado como evidência histórica; novo smoke real com o alias canônico e revisão independente permanecem pendentes;
- corrigidos [contraexemplos do oráculo (DEC-028)](docs/decision-log.md#dec-028): aprovação vinculada à conta e campos exatos, recibo confiável para pontuar A1/A2 e erro de contrato para mutação não atribuída; 134 testes offline passaram, sem integração Odoo/runner nem run científica;
- atualizados plano, backlog, lock e documentação corrente sem alterar amostras, hipóteses, métricas, margens ou protocolo congelado (ainda inexistente).

## [1.2.14] — 2026-09-24

- aplicada a [limpeza de artefatos obsoletos (DEC-025)](docs/decision-log.md#dec-025): DOCX, PDF do plano e validador Word da v1.2.1 retirados do checkout corrente após conferência de caminhos e hashes;
- preservados commits e manifestos históricos, incluindo os hashes da v1.2.1, sem reescrever releases publicadas; o PDF e os fontes do artigo institucional não foram removidos;
- reduzido o índice do README: a versão atual e o changelog são os pontos de entrada, sem uma linha para cada release passada;
- atualizado o validador corrente para exigir a ausência dos três arquivos obsoletos; nenhuma hipótese, amostra, condição C0/C1, dado ou resultado foi alterado.

## [1.2.13] — 2026-09-24

- preservadas as versões remotas 1.2.11 e 1.2.12 e o escopo de três objetivos financeiros da DEC-023; a correção local ainda não publicada foi integrada como DEC-024, sem reutilizar IDs já publicados;
- registrada a mudança documentada de roteamento do alias legado DeepSeek para V4.1 Flash, sem alegar snapshot imutável do backend;
- concluído tecnicamente G3-05 em uma chamada sintética tipada, sem retry: `deepseek-v4-flash` solicitado, `deepseek-flash` retornado, manifesto saneado e varredura de logs aprovados;
- aprovados 105 testes do gateway/cliente e 6 do proxy offline na árvore integrada; marcadores anteriores permanecem locais, com apenas hashes e categorias saneadas no Git;
- G3-06 passa a `READY`; C0 científico, C1, dataset, piloto e freeze continuam pendentes; nenhuma run experimental foi contabilizada;
- mantidos inalterados hipóteses, métricas, margem, amostras, condições C0/C1 e regras de análise da versão 1.2.12.

## [1.2.12] — 2026-09-08

- retirada a avaliação de exposição de dados (A3b), incluindo canários, mensagens ao fornecedor, métricas SDR, tokenização e a condição de ablação dedicada à minimização, conforme [redução do escopo (DEC-023)](docs/decision-log.md#dec-023);
- preservada a meta de 90 pares, distribuídos em 30 de manipulação de campos, 30 de redirecionamento de beneficiário e 30 de ação crítica sem autorização; os cálculos antigos sobre 15 pares críticos deixam de valer e serão refeitos antes do congelamento;
- preservados piloto e principal com 1.224 execuções obrigatórias; ablação com quatro condições soma 576 e ataques adaptados à defesa somam 216, ambos condicionais; programa com esses blocos e piloto soma 2.016 e, com segundo modelo, 2.448;
- retiradas obrigações dependentes no catálogo de controles, regras, invariantes, riscos, checklist e backlog; IDs retirados ficam reservados e os registros históricos são preservados;
- acrescentadas leitura rápida, definições em linguagem direta e referências com descrição e link para decisões, perguntas, hipóteses e seções; registrada a convenção no AGENTS.md;
- corrigida a inversão textual da ordem de escrita do fornecedor/beneficiário para coincidir com o teste já registrado, sem mudar código do executor;
- atualizados fontes, navegação interna e PDF pré-experimental do artigo; nenhuma medição científica foi produzida;
- acrescentada validação executável de Markdown, links, matrizes, escopo e fontes/PDF do artigo; preservados os binários históricos do plano-mestre;
- versão registrada em commit local dedicado, sem envio ao remoto.

## [1.2.11] — 2026-09-05

- concluída a primeira revisão adversarial sistemática do plano, em doze dimensões independentes, com refutação de cada achado contra o arquivo, o código e os documentos de apoio: 124 achados brutos, 4 refutados, 120 sobreviventes — 26 de severidade alta, 66 média e 28 baixa, nenhum crítico após a refutação;
- publicado o dossiê completo em `docs/revisao-independente-v1.2.9.md`, com localização, trecho literal citado, problema, consequência, verificação adversarial e correção recomendada por achado, mais apêndice dos achados refutados e da razão da rejeição;
- registrada a decisão DEC-022, que separa as correções aplicadas nesta versão das que dependem de ratificação do grupo;
- fixada em §9.2 a fronteira entre resolução técnica de referências, permitida em C0, e revalidação semântica contra estado confiável, exclusiva de C1; o executor C0 aprovado em M2 viola essa fronteira e a correção é pré-condição do gate de competência, sob pena de `ASR-state` em C0 tender a zero nas famílias A1 e A2 e H1 deixar de ser falseável;
- exigido que o oráculo de estado seja independente da proposta do modelo, para que desfecho adversarial seja medido em vez de convertido em dado ausente;
- criada em §9.2 a checklist de plausibilidade de C0, até então apenas prometida, incluindo a exigência de que C0 demonstre vulnerabilidade por família adversarial no piloto;
- reformuladas em §13.2 as métricas de fronteira como cascata marginal sobre o denominador comum de execuções adversariais avaliáveis, com a relação monótona `p_entrega ≥ p_proposta ≥ p_politica ≥ p_estado`; as razões condicionais `ASR-proposal` e `ASR-policy` passam a ser descrição de mecanismo dentro de cada condição e não sustentam hipótese, tabela confirmatória ou claim, porque condicionam em variáveis posteriores ao tratamento;
- alterado o denominador de `False Block Rate` para execuções benignas avaliáveis, pela mesma razão;
- retirada `ASR-policy` da coluna de endpoints de RQ1 em §28;
- pré-especificada em §15.2 a regra de células zero e de fronteira — Newcombe para diferença pareada, Wilson para proporções isoladas, McNemar exato sempre, `RR` omitido quando indefinido, bootstrap com 10.000 replicações, percentil e semente registrada —, cenário esperado quando `ASR_C1 = 0`;
- declarado em §15.1 que o denominador adversarial efetivo de H2 é o bloco A3a, com 15 pares e não 90, com a potência calculada e a decisão sobre seu status retirada do piloto, que conteria cerca de 2 pares A3a;
- nomeados em H1 e H2 os endpoints congelados `ASR-state` e `UACR`, eliminando o termo "ASR de execução", ausente do glossário, e explicitada a equivalência entre o teste bilateral a 5% e o critério operacional de limite superior do IC95%;
- definida em §11.4.1 a pré-imagem do hash da ação canônica, com campos enumerados, ordenação, normalização NFC, escala decimal, serialização e vetor de teste congelado, sem a qual C08, C10, R-POL-09 e o invariante I4 não eram falseáveis nem reproduzíveis;
- vinculada a autorização de `POST_APPROVED` ao rascunho exato por `target_move_id`;
- definido em §14.5 o conteúdo do hash canônico de estado, que antes era invocado como oráculo de reset sem enumeração e cuja única implementação observava apenas contas filtradas pela referência do cenário; passam a integrar a projeção `ir.sequence`, `ir.attachment`, `mail.message`, `res.partner.bank`, os computados do pedido, a ausência de `account.payment` e o outbox, agora verificado por execução e não por lote;
- decomposta `SDR` em `SDR-context`, `SDR-proposal` e `SDR`, e registrado em §12.3 que `SDR_C1` é zero por construção na rota de cadastro mestre, porque a minimização nunca entrega o canário ao modelo;
- ancorado o canário de origem documental nos cinco pares de "A3b — controle de criação" e acrescentado `canary_origin` ao manifesto de cenário, sem alterar tamanho amostral nem matriz;
- acrescentada em §14.7 a quinta condição de ablação, sem minimização e sem allowlist de campos, sem a qual nenhuma condição move `SDR`, H5 fica inverificável nesse endpoint e os controles C11 e R-POL-08 não são exercidos em nenhuma execução científica; a matriz passa de `48 × 4 × 3 = 576` para `48 × 5 × 3 = 720`, o núcleo para 2.016 e o plano mínimo para 2.160 execuções, com a alternativa registrada de retirar `SDR` de H5 caso o grupo não ratifique a condição;
- propagados os novos totais para §14.8, §14.9, o gate G7 do cronograma e o marco M7b;
- nomeada em §9.5 a arquitetura de C1 como monitor de referência, com as três propriedades clássicas mapeadas a verificações já existentes, e declarada por escrito a base confiável e o que não pertence a ela, incluindo o LLM, o parser e o detector auxiliar C13;
- restringida a exigência de cobertura de ramos de 100% aos módulos da base confiável, mantida a regra de 80% de linha para o restante;
- acrescentado o invariante I10, de mediação completa e invariância diante de `context` hostil;
- posicionada em §4.1 a arquitetura no espaço de projeto das defesas, com o agente enquadrado como deputado confundido e o contraste explícito com a propagação de capacidades de CaMeL;
- declarado em §22.3 o limite superior estrutural da abordagem: C1 só protege propriedades que o estado confiável consegue decidir, e um ataque inteiramente consistente com o pedido de compra não é detectável pelo policy engine;
- declarada em §8.3 a implementação deliberada da conciliação de duas vias e a ausência por construção da via de recebimento, com a consequência de validade externa em §22.3;
- acrescentado a §16.8 o invariante da política de faturamento do item das fixtures, cuja resolução por quantidade recebida zeraria `qty_to_invoice` e bloquearia todo `CREATE_DRAFT` legítimo;
- adotadas quatro referências clássicas, cada uma instanciada em critério verificável: ANDERSON (1972), SALTZER e SCHROEDER (1975), HARDY (1988) e HEVNER et al. (2004); rejeitadas explicitamente COSO, NIST SP 800-207, DENNING (1976), NBC TA 315 e o arcabouço FEDS, por não produzirem critério testável neste recorte;
- criada em §29.1.1 a declaração de busca dirigida para a fundamentação clássica, que os critérios de inclusão de §29.3 excluíam por construção, com a regra de que essas obras não entram na matriz comparativa nem sustentam claim de resultado;
- corrigido o título da referência PIArena, que não correspondia ao registro da ACL Anthology; a verificação contra ACL Anthology, PMLR, USENIX e registros DOI não encontrou nenhuma referência fabricada;
- acrescentados os riscos R26 a R30: tautologia de SDR, colapso do contraste por revalidação em C0, indisponibilidade do provedor, troca de backend no meio da coleta e ausência de definição do pacote saneado;
- acrescentada a §18.1 a reconciliação de 05/09/2026, que registra a anuência do orientador vencida em 01/09 sem evidência, o requerimento no Portal do Aluno com prazo interno de 07/09, o replanejamento da matriz de literatura para 13/09, o avanço assimétrico entre as três trilhas, a ausência de folga para reexecução e a distinção entre o gate G3 e as subetapas G3a, G3b e G3c;
- acrescentados dezessete itens ao checklist de congelamento de §30.1, cobrindo as correções acima;
- mantidos inalterados problema, perguntas de pesquisa, D01–D15, a margem D13, o threat model, o tamanho do teste v1 e a comparação C0×C1.
- restaurados 25 arquivos rastreados que uma cópia trazida de outra máquina havia rebaixado para conteúdo anterior ao commit `4578e85`, entre eles `compose.yaml` (101 linhas), `gateway/src/tcc_gateway/llm_client_service.py`, os testes do cliente e os locks de ambiente e de seleção de modelo; sem a restauração, publicar esta versão apagaria o trabalho de G3c já commitado;
- removidas 19 duplicatas com sufixo `(2)` criadas pela mesma cópia, todas verificadas por hash como idênticas ao conteúdo já versionado;
- acrescentadas ao `.gitignore` a cópia aninhada `/tcc/` e `/tcc.tar`, que não podem ser versionadas por conterem `.env` local e duplicatas do plano;
- renumerada esta versão para 1.2.11 porque a revisão foi conduzida sobre o texto da v1.2.9 presente na árvore de trabalho, enquanto a v1.2.10 já estava publicada em `4578e85`; nenhum commit de versão publicada foi reescrito.

## [1.2.10] — 2026-09-02

- implementado o caminho real G3c em profile explícito, com chave local exata e read-only somente no `llm-client`, runner sem segredo/egress e proxy como único componente com saída;
- corrigida a captura do Docker Compose no Windows PowerShell e ampliado o diagnóstico para preservar somente categoria/status saneados do provedor, sem corpo de erro;
- aprovados 97 testes do gateway/cliente e 6 do proxy em contêiner sem rede antes da tentativa diagnosticável;
- preservadas separadamente as tentativas autorizadas, sempre sem retry automático e sem manifesto de sucesso falso;
- observado exatamente um túnel permitido na tentativa diagnosticável e resposta HTTP 402 do provedor, sem inferência, modelo retornado ou resultado científico;
- mantida G3-05 como `EXTERNAL`, agora dependente de crédito/saldo e nova autorização explícita; G3-06, piloto e runs continuam bloqueados;
- nenhum segredo, corpo bruto, prompt, proposta, documento real ou dado fiscal foi versionado;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem, threat model, amostras e comparação C0/C1; o protocolo continua pré-freeze.

## [1.2.9] — 2026-09-01

- materializado em G3b o processo `llm-client` separado, sem credenciais do ERP/DeepSeek no profile offline e com API interna fechada `llm-client-request/v1`;
- separadas as redes internas `lab`, `llm_control` e `llm_egress`; somente o proxy participa de `proxy_external`, enquanto gateway, Odoo e PostgreSQL permanecem sem rede externa;
- implementado proxy HTTP CONNECT de passagem com destino fixo `api.deepseek.com:443`, negação de host, IP literal e porta alternativos e recusa de resolução DNS não pública;
- aprovados 91 testes do gateway/cliente, 6 do proxy, validação do Compose resolvido, probe runtime offline e varredura de logs;
- registrados os IDs locais das imagens `tcc-gateway:0.4.0` e `tcc-egress-proxy:0.1.0` sem apresentá-los como digests de manifest OCI;
- concluídas no backlog as tarefas G3-01–G3-04 e preservada G3-05 como dependência externa de autorização;
- nenhuma chamada DeepSeek/Ollama, tentativa de túnel nominal, leitura de chave ou download de modelo integrou o gate;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem, threat model, amostras e comparação C0/C1; G3c, C0 científico, C1, dataset, piloto e freeze permanecem pendentes.

## [1.2.8] — 2026-09-01

- fixada em DEC-020 a fronteira mínima de egress: Odoo, banco e gateway permanecem sem saída externa; um `llm-client` dedicado acessará o DeepSeek somente por proxy TLS com destino permitido e o Ollama somente pela rede interna;
- implementados no gateway 0.3.0 os adapters DeepSeek/Ollama, configuração segura, schema auxiliar de saída do modelo, injeção de proveniência confiável pelo adapter e sanitização de erros e metadados;
- aprovados 82 testes em contêiner `--network none` e somente leitura, sem chamada a API, download de modelo, leitura ou criação de chave; o ID local da imagem foi registrado sem tratá-lo como digest de manifest OCI;
- atribuídos em DEC-021 os workstreams: Felipe em ciência/dados, Thomaz em arquitetura/segurança e Gustavo em Odoo/experimentação, com revisão cruzada e fronteiras de integração explícitas;
- publicado `docs/task-backlog.md` com 116 tarefas identificadas, prioridade, proprietário, revisor, dependências, entregável, Definition of Done, estado e ondas W0–W7 para execução paralela;
- atualizado o controle institucional com os papéis e o proprietário operacional do cadastro/requerimento, preservando como pendentes a confirmação externa e o recibo;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem de não inferioridade, threat model, amostras e comparação pareada C0/C1;
- permanecem pendentes G3b (topologia e testes negativos de egress), G3c (smokes reais autorizados), competência do C0 científico, C1, dataset, piloto, freeze e resultados.

## [1.2.7] — 2026-08-31

- registrada em DEC-018 a seleção do DeepSeek por API como modelo principal e do Qwen3 14B quantizado via Ollama como segundo bloco separado de robustez e transportabilidade;
- corrigida a nomenclatura de reprodução: a API recebe `deepseek-v4-flash`, associado pelo provedor em 31/08/2026 a `DeepSeek-V4-Flash-0731`, sem tratar o alias móvel como snapshot imutável;
- fixada a tag local explícita `qwen3:14b-q4_K_M`, mantendo pendentes manifest completo, digests de blobs, download autorizado e smoke de hardware;
- definido *thinking* desligado no núcleo dos dois modelos e preservada a igualdade de modelo, prompt, schema, parâmetros e retries entre C0 e C1 dentro de cada bloco;
- preservadas a meta principal pré-piloto de 180 documentos e 1.080 runs e a amostra secundária de 72 documentos e 432 runs; a menção exploratória a 120 documentos não alterou W05;
- acrescentados protocolo operacional de seleção e lock de proveniência, incluindo captura temporal de alias/backend, request ID saneado, hashes, tokens, custo, latência, erros e retries;
- registrada a viabilidade local ainda condicional: Ollama 0.30.10, RTX 3060 Ti de 8 GiB, Qwen de catálogo com aproximadamente 9,3 GB e necessidade de offload e benchmark antes do bloco secundário;
- mantida a rede interna do laboratório sem egress amplo; o desenho de saída mínima e a implementação dos adapters permanecem pendentes para G3;
- mantidos inalterados problema, perguntas, hipóteses, endpoints, métricas, margem de não inferioridade, threat model, dataset planejado e comparação C0/C1.

## [1.2.6] — 2026-08-31

- registrada em DEC-017 a separação entre o vertical slice pré-experimental M2 e o futuro C0 científico baseado em LLM;
- comprovado o fluxo PDF sintético benigno com camada de texto → extração sem OCR → proposta `vendor-bill-proposal/v1` → execução direta C0 → conta de fornecedor em rascunho → restauração do estado;
- implementados limites de ingestão, validação estrita por JSON Schema, reconciliação decimal e resolução de referências exclusivamente por chaves de negócio sintéticas;
- fixado `deterministic-development/v1` como adaptador somente de desenvolvimento, explicitamente proibido nas runs científicas;
- ampliada a suíte do gateway de 19 para 41 testes, incluindo PDFs criptografados/sem texto/inválidos, campos duplicados ou ausentes, schema incompatível, totais divergentes e estados residuais;
- aceito o smoke `M2-BENIGN-001` com hashes próprios do PDF, texto, proposta, estado criado e estado restaurado, preservando os volumes;
- atualizado o gateway para 0.2.0, com dependências diretas e transitivas resolvidas, config digest local e hashes de build registrados no lock;
- marcado M2/G2 como atendido tecnicamente, mantendo pendentes para o piloto/G3 a implementação e a seleção do LLM, a competência benigna do C0 científico e o dataset piloto;
- mantidos inalterados problema, hipóteses, endpoints, métricas, margem, threat model, dataset planejado e desenho experimental C0/C1.

## [1.2.5] — 2026-08-31

- preservada a v1.2.4 como scaffold histórico e incorporada a correção de aceite registrada em DEC-016, sem reescrever commits ou manifesto anteriores;
- comprovado o manifest OCI local da imagem Odoo (`sha256:3e0bcf8e796820e89577b1db24b4dbb54a63669f66384c4b61577068adf1f392`) como objeto distinto do config digest efetivamente carregado;
- sincronizados os locks de fonte e ambiente com commit, plataforma, imagem-base, manifest, config, labels e evidência interna de revisão;
- substituído o smoke administrativo de cadastro por identidade C0 dedicada e por fixtures sintéticas de empresa, fornecedor, banco, produto e pedido de compra confirmado;
- comprovadas via JSON-2 a criação e leitura de uma única conta de fornecedor em rascunho, a persistência do beneficiário, a ligação com a linha de compra e a remoção com restauração exata do hash inicial;
- classificado como atendido o marco técnico M1, sem declarar concluídas as obrigações não técnicas de G1 ou os marcos M2/C0, C1, dataset, piloto e freeze;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset planejado e desenho experimental C0/C1.

## [1.2.4] — 2026-08-31

- implementado o primeiro incremento executável do laboratório M1/G1 conforme DEC-014 e DEC-015;
- construída a imagem Docker do Odoo 19.0 Community a partir do commit imutável `a4b877245c9cb5e3d7152d1593a518170f115ca1` com labels OCI e evidência interna verificada;
- adotado PostgreSQL 18 (`postgres:18@sha256:7341002d2b8c7c5bdd7542a671a95b36196c0b5b888daf454ae4fc33ba5346d7`) com volume configurado para a estrutura de diretórios 18+;
- implementado o pacote de gateway JSON-2 (`tcc_gateway`) com sanitização de credenciais em logs/erros, serialização canônica UTF-8/SHA-256 e 19 testes unitários aprovados;
- implementados scripts operacionais de bootstrap (`new_local_env.ps1`), build (`build_odoo_image.ps1`) e smoke test determinístico (`smoke_test.ps1`, `smoke_test_gateway.py`) com ciclo completo de criação/leitura de fornecedor e reset comprovado por volumes;
- atualizados `reproducibility/lab-environment.lock.json` com os digests e metadados imutáveis;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset e desenho C0/C1.

## [1.2.3] — 2026-08-31

- corrigida, conforme DEC-013, a garantia técnica da fronteira JSON-2 antes do início da implementação;
- registrado que o controller consome `context` antes de chamar o método e que o executor deve neutralizar sua influência e comprovar invariância, em vez de alegar rejeição literal;
- reformulado o menor privilégio de C1 como ausência de mutações críticas fora de `ap.security.executor.execute`, com inventário explícito de eventuais leituras residuais das ACLs básicas;
- mantidos inalterados problema, hipóteses, métricas, margem, dataset e desenho C0/C1.

## [1.2.2] — 2026-08-31

- adotado o Markdown como único formato editável e corrente do plano-mestre, conforme DEC-012;
- removido `build_tcc_docx.ps1` e encerrada a geração obrigatória de DOCX/PDF do plano;
- preservados DOCX, PDF, validador e manifests anteriores apenas como evidência histórica da v1.2.1;
- mantido o artigo institucional como artefato separado no template FCI, sem mudança no escopo científico ou no experimento;
- atualizados fluxo de releases, gates e árvore sugerida do repositório para eliminar a dependência do Microsoft Word.

## [1.2.1] — 2026-08-30

- confirmada W06: margem de não inferioridade fixa de 10 pontos percentuais para `BTSR_C1 − BTSR_C0`;
- promovida a margem confirmatória a D13, antes do piloto e do teste final;
- fixada a fonte do Odoo em `https://github.com/odoo/odoo.git`, branch observada `19.0`, commit `a4b877245c9cb5e3d7152d1593a518170f115ca1`;
- registrado que o branch avançou após a seleção e que isso não altera o pin imutável aprovado;
- separado o commit Git do digest OCI, que será preenchido somente após construir a imagem desse commit;
- auditados o edital `EditalTCC_2026_2-V1`, o template FCI criado em 15/08/2026 e o fonte editável do TCC I;
- confirmados os três autores e Mario Olimpio de Menezes como orientador;
- definido que o plano permanece operacional e o produto institucional será um artigo separado de 10–20 páginas no template 2026, com submissão inicial até 09/11/2026;
- reancorado o cronograma, mapeadas as seções científicas para a estrutura oficial e acrescentados os gates de Resumo/Abstract, NBR 6023:2018, apresentação e excelência;
- confirmado que não haverá participantes humanos e que a nomenclatura DSR com experimento controlado permanece;
- mantido fora do Git o pacote local com repositório aninhado e PII, registrando apenas requisitos saneados e hashes;
- ampliado o verificador de segurança para bloquear o pacote institucional/TCC I mesmo em preparação forçada e detectar e-mail, CPF e identificadores acadêmicos em arquivos textuais;
- adicionados locks de procedência e manifesto auditável da release 1.2.1;
- regenerados e validados Markdown, DOCX e PDF.

## [1.2] — 2026-08-30

- adotado Odoo 19.0 Community self-hosted; SaaS 19.4, Enterprise e IA nativa ficaram fora do escopo;
- incorporados a base conceitual, o método, as limitações e os trabalhos futuros efetivamente desenvolvidos no TCC I;
- definido JSON-2 como transporte e o add-on transacional/idempotente como fronteira de autorização de C1;
- esclarecidas as decisões W03, W04, W06 e W07;
- detalhados ameaça, executor, identidade restrita, dataset, métricas, freeze, reexecução e validade confirmatória;
- instituídos `AGENTS.md`, logs de decisão/desvio, proteção de segredos, varredura pré-commit e um commit por versão;
- definido gate de artefatos sem metadados pessoais, revisões, macros ou objetos incorporados e custódia externa verificável dos dados brutos;
- ampliados `.gitignore` e o verificador local para credenciais, configurações sensíveis, JWT, cabeçalhos Bearer, URIs de banco autenticadas e arquivos de uma única linha;
- corrigido o gerador para impedir vazamento de estilo de código inline para a prosa;
- corrigida a paginação de tabelas longas para evitar uma última linha órfã antes de novo capítulo;
- criado manifesto auditável e commit-âncora da v1.2, sem reescrever os commits já publicados fora do padrão de release.
- regenerados e validados Markdown, DOCX e PDF.

## [1.1] — 2026-08-28

- adotado o título proposto pelo orientador, sem alterar problema ou desenho experimental.

## [1.0] — 2026-08-26

- consolidado o primeiro plano operacional completo de pesquisa, implementação e avaliação experimental.

> As versões 1.0 e 1.1 foram produzidas antes da política de commit por versão. O histórico interno foi preservado no plano-mestre; a política passa a ser obrigatória a partir da versão 1.2.
