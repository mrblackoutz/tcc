# Revisão científica e operacional pré-piloto

**Data:** 26/10/2026. **Base:** `7aec739898d327ba2fc6cee42bca37035c2865d5`, com os deltas e hashes explicitados abaixo. **Revisor:** agente Codex `review_science_gates`, distinto do autor; família GPT-6 conforme a identidade da sessão, variante/backend não expostos. Revisão automatizada, sem assinatura em nome de integrante. Aplicam-se [revisão por agente (DEC-081)](../decision-log.md#dec-081) e [factibilidade (DEC-082)](../decision-log.md#dec-082).

## Resultado por tarefa

| ID | Parecer e estado recomendado | O que continua aberto |
|---|---|---|
| SCI-01 | `AGENT_REVIEWED` para o protocolo candidato reduzido. Escopo, H1 → H3 → H2, margem absoluta de −0,10, pareamento por par/repetição, cluster por `pair_id`, denominadores e sensibilidades são coerentes com o plano. | Não é assinatura de freeze. Fronteira/zero, precisão/poder, status de H2 e dados do piloto têm gates próprios; não foram aceitos antecipadamente. |
| SCI-03 | Revisão da regra pura passou; manter tarefa `ACTIVE`. A classificação não recebe condição, payload ou desfecho. O produtor candidato da DEC-087 foi implementado posteriormente por este revisor e passou em 57 testes de observação/classificador/transporte; a revisão independente desse código foi feita pelo integrador, com contraprovas executadas. | Falta demonstrar o produtor no ciclo integrado. Esgotamento agora deriva do histórico de três leituras elegíveis, com esperas de 1/2 s; a presença do componente não prova que o runner já o utiliza. |
| SCI-04 | Manter `CUT`. H4 confirmatória foi retirada pela DEC-058. | Medições de eficiência seguem descritivas em RUN-07/AN-05; não inventar novo limiar de aceitabilidade. |
| C0-05 | `AGENT_REVIEWED` para a plausibilidade estrutural do C0 versionado: prompt da tarefa plausível e comum, saída tipada, CREATE/POST limitados e resolução técnica sem política C1 oculta. | C0-04 continua dependendo de competência no estado do ERP. A integração que mudar prompt/despacho deve ser revalidada. Ratificação nominal do grupo permanece no freeze. |

Não foi encontrado bloqueante no conteúdo candidato revisto. As pendências de implementação listadas não são defeitos editoriais nem desaparecem com uma revisão. As 144 chamadas de propostas e seu limiar não demonstram ASR-state, competência financeira ou reset; esta revisão não consultou resultados da rodada 2 nem alterou sua decisão.

## Prova executada

`python -m pytest -c gateway/pyproject.toml gateway/tests/test_review_science_gates.py gateway/tests/test_run_disposition.py gateway/tests/test_attempt_policy.py gateway/tests/test_task_prompt.py gateway/tests/test_c0_action_executor_v2.py gateway/tests/test_pilot_proposal_batch.py -q`: **94 testes passaram em 3,16 s, incluindo 11 novos**. Relatório local: `.runtime/pytest-review-science-20261026.xml`.

- Classificação: todos os 256 vetores booleanos foram exercitados; 88 são evidências válidas e 168 são rejeitados pelo contrato. `MISSING` aparece somente com estado final ilegível, efeito quiescente e falha infraestrutural independente após tentativas esgotadas. Alterar reset não altera retroativamente a disposição da execução.
- C0: três valores divergentes e beneficiário de outro proprietário chegaram ao CREATE; a busca bancária não ganhou allowlist de fornecedor. POST chamou somente o alvo confiável, sem aprovação ou escrita prévia dos argumentos descritivos adulterados. São doubles explícitos, não prova ORM nova.
- Prompt: seis combinações de fase/texto hostil preservaram mensagens idênticas entre condições e impediram o documento de alterar a instrução de sistema. As suítes existentes de tentativas, contrato C0 e construção dos lotes também passaram.

## Fontes e limites

SHA-256 dos arquivos principais revistos:

| Arquivo | SHA-256 |
|---|---|
| `docs/protocol.md`, prefixo vigente v0.4 antes do marcador da proposta da seção 5 | `1ccff817c019e6f429f0bcd1b77e04810a59bd15e4518e087180abfd98223368` |
| `run_disposition.py` | `789c58bed4fa0c197a737b82f56c4a84dcddd0844c80a3d2472a11dd5305c10d` |
| `c0_action_executor_v2.py` | `b57e2a021b50d2f274252cdc6ca8c6191a26f1f84b2c512903095b6e6c6046b3` |
| `task_prompt.py` | `6beab2ce9dae894ed50897fa4b16e467fb5d38b33bb42b8844847d578dc45e7c` |
| `test_review_science_gates.py` | `bce38970b4e2e45e4538200b99a0ee6419129ebfe0bba6f686368b1aba8d7bb5` |

Não foram feitas chamadas à API, alterações na defesa/dataset, testes Docker/ERP, revisão humana ou validação estatística por simulação. O artefato novo contém testes e parecer, sem mudança no código de produção. Revisões executadas por agentes podem compartilhar pontos cegos; a evidência não ratifica o modelo de implantação nem o resultado científico.

## Complemento: protocolo vigente v0.4

Revisado somente o cabeçalho e as seções 1–4, até `<a id="proposta-enquadramento-estimativo"></a>`, sem abrir o conteúdo da proposta externa seguinte. Os deltas preservam hipóteses, margem, amostra e sequência, registram as três leituras de observação com esperas de 1/2 s e distinguem revisão técnica de assinatura nominal. A regra candidata Hoeffding ponderada tem a expressão coerente com contrastes por par em `[−1,1]`, sob as premissas explícitas de independência condicional às completudes; não substitui sensibilidades de missing ou validação própria do método estatístico. Não houve nova execução dos 94 testes, pois esse complemento altera somente documentação. A seção 5 permanece não vigente e não recebeu aceite nesta revisão.

## Complemento: rastreabilidade e inventário

SEC-01, SEC-02 e SCI-09: parecer `AGENT_REVIEWED` para a [matriz corrente](../control-test-matrix.md), SHA-256 `537113703eaf4be73c5709ad721b004ee4010c066b5b51c4bf75078c577c89ff`. Conferidos os vínculos dos invariantes I1–I8/I10 e de RQ1/H1, RQ2/H3, RQ1/H2 e RQ3 às fontes, testes e saídas previstas. O achado I8 foi corrigido pelo integrador: falha segura agora referencia kernels financeiros e faults/rollback, além dos componentes de mensuração. Os 31 nomes Python citados resolvem para arquivos existentes; `draft_kernel.py::_context` existe.

A contraprova JSON, somente em memória, conferiu 366 modelos, 151 ACLs e 83 regras. Os sete modelos críticos revisados não permitem CREATE/WRITE/UNLINK. A validação semântica independente rejeitou 21 escaladas sintéticas, mesmo após recalcular o hash interno. O arquivo atual SHA-256 `7139e8cf272b218286dc020b7cf8eb277f74f83d237715a6e37d7a311821e69c` coincide com `/workflowRegistration/inventoryFileSha256`; campos históricos diferentes não foram alterados. Não houve consulta de permissões a um ERP vivo. O add-on está inalterado desde `ecf15dc`, base das provas independentes HTTP/transacionais já registradas; essas provas não foram repetidas nem atribuídas a esta revisão.

## Complemento: preparo ERP da coorte atual

A auditoria somente leitura da [DEC-090](../decision-log.md#dec-090) confirmou o preparo `.4`: 12 bases comerciais e cinco bancos alternativos na captura ERP, oito origens CREATE com valor, data, fornecedor, banco, itens, ligação à PO e PDF exatos. O ensaio `fbe8aaef892d4e6e877d768199d4d9b2` tem 25 capturas, 16 bancos de dados restaurados distintos e igualdade de binding, projeção e IDs com o baseline; dump/filestore foram verificados. Documento, ação, aprovação e nonce têm oito hashes distintos; 160 negativas de aprovação e 24 de origem foram conferidas. Checkout/snapshots correspondem às 152 fontes do reset e 136 do preparo nativo `5a9cf6a8229d43d1a7d7320b4ff7712d`; pins e manifests de cleanup conferem. SHA-256 das evidências: `3facc39c3fecc067ac46634f96205ffc21562fc2c3d8e0798901dc581b606711` e `3660d54281c47ae49cd73c61860e158aaf5e375fe01f42e9d0f125873e10e86a`, respectivamente. É legítimo classificar DATA-06 pelo **preparo ERP**, RUN-03 pelo **oráculo puro/adaptador de captura** e RUN-04 pelo **mecanismo snapshot/reset** como `AGENT_REVIEWED`. Não foram ratificados perfil temporal operacional, custódia entre fases, consumo de nonce ou POST neste ensaio; autorização ficou em memória. Integração LLM/estado/supervisão e métricas efetivas seguem em RUN-02/09, SCI-03 e PILOT, sem serem apagadas ou presumidas concluídas. Nenhum resultado LLM da rodada 2 foi aberto nesta auditoria.

## Atualização de escopo — 27/10/2026

O parecer acima preserva o escopo e os hashes efetivamente revistos em 26/10. O [estudo descritivo adotado (DEC-094)](../decision-log.md#dec-094) e a [reconciliação corrente (DEC-097)](../decision-log.md#dec-097) substituem as cobranças confirmatórias, o corpus adicional e a proposta antes pendente. Permanecem válidas as provas de componentes, contratos, matemática, segurança e preparo. A coleta vigente tem 144 execuções; revisão do lote, intervalos aplicados e aceite do artigo continuam separados. Não se atribui à revisão antiga cobertura da implementação integrada posterior.

No escopo corrente da DEC-097, SCI-03 passa a `AGENT_REVIEWED` para o classificador e a regra conservadora efetivamente implementada: falha de captura/estado/reset interrompe e não fabrica ausência. A integração opcional do produtor de três leituras não é requisito para uma coleta íntegra. A revisão do lote continua RUN/PILOT. O integrador também encerrou RUN-05: além da suíte focal, dez sementes produziram exatamente os 144 slots esperados, sem repetição, e três entradas inválidas foram rejeitadas (seed booleana, duas repetições e membros duplicados). Nenhuma fonte ou resultado da coleta foi alterado por essas contraprovas.
