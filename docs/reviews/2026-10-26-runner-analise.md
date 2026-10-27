# Revisão de runner, oráculo e análise — 26/10/2026

Revisor: agente Codex distinto do autor (`review_runner_stats`), família GPT-6; variante/backend não expostos. Base `7aec739898d327ba2fc6cee42bca37035c2865d5`. Revisão automatizada, sem assinatura humana. Não foram abertos resultados, outputs ou análises da rodada 2, nem alterados limiar, hipóteses, prompt ou dataset.

**Resultado do núcleo existente:** 706 testes passaram em 75,34 s nas suítes de tentativas, histórico terminal, oráculo, vínculo dataset/oráculo, registro v4, store e recuperação de reset; zero falhas, erros ou skips. Relatório privado `.runtime/pytest-review-runner-20261026.xml`. Mais 16 contraprovas independentes, com fixtures sintéticas: erros do modelo com estado legível permanecem avaliáveis; resultado incerto sem proposta bloqueia o lote; quase-acerto de linhas não vira tarefa concluída; sucesso após retry conserva a incerteza; falta de observação da aprovação continua bloqueando após reset; alteração de classificação é rejeitada; sobrescrita preserva os bytes originais. Nenhuma chamada externa ou efeito no ERP. Nenhum bloqueante encontrado nesses componentes.

| Item | Revisão concluída | O que ainda impede concluir a tarefa inteira |
|---|---|---|
| RUN-01 | Contrato/derivação do registro v4 | Integração operacional, observações e supervisão do ciclo completo; campos/gates restantes da SCI-03 |
| RUN-03 | Oráculo e vínculo independente às expectativas | Aquisição das fixtures/efeitos reais no ciclo piloto; não inferir efeito pelo output |
| RUN-06 | Elegibilidade de retry, orçamento e preservação de erros | Política operacional de observação e supervisão integrada; não classificar resultado incerto automaticamente como missing |
| RUN-08 | Escrita exclusiva, integridade e journal local de reset | Retenção/custódia externa não foi demonstrada por essa revisão |
| STAT-01 | Lacuna da base resolvida pela implementação da DEC-089 abaixo; revisão matemática independente concluída | Ratificação nominal de freeze; recomendado `AGENT_REVIEWED`, não aceite humano |
| AN-01/02 | Validação de entrada/denominadores e estimadores exercitados com dados sintéticos | Aplicação ao conjunto experimental coletado; não são análises finais concluídas |

Os componentes acima tiveram sua revisão técnica encerrada; os estados globais RUN continuam `ACTIVE`/`WAIT` enquanto seus entregáveis faltantes não existirem. Não há aceite científico, humano ou de freeze. A implementação de STAT-01 é tratada separadamente, após decisão anterior ao código; as tarefas de análise final AN-01/02 continuarão dependendo do conjunto experimental coletado.

## Implementação sintética de STAT-01 — DEC-089

Após a decisão registrada antes do código, foram criados `paired_analysis.py`, `test_paired_analysis.py` e a CLI `analyze_synthetic_runs.py`, todos sem dependências novas. Foram aprovados 27 testes em 0,49 s e dois ensaios de 10.000 reamostragens: uma tabela inteiramente sintética de 360 linhas/30 pares e uma fronteira de 90 pares sem eventos. Nesta última, o IC conservador foi `[-0,2863129389; 0,2863129389]`; o percentil degenerado `[0,0]` não foi usado para inferência.

Os contrastes mantêm slots pareados, enquanto as taxas descritivas conservam todos os avaliáveis. Elegibilidade crítica é explícita e estável por par, nunca inferida de métrica falsa. Agenda independente pode ser fornecida por `expected_pair_ids`; sem ela, o relatório declara que não comprovou a ausência de um par inteiro omitido. Observações não monotônicas na cascata são conservadas e contadas como diagnóstico, sem descartar uma violação real. Estão implementados BCa por cluster, percentil de sensibilidade, Hoeffding condicional à completude em fronteiras, McNemar exato suplementar por cenário com três repetições, ITT, cenário conservador, exclusão de falha fechada, margem estrita `−0,10` e sequência H1→H3→H2. Não há concessão automática de aceite confirmatório ou de freeze.

Reprodução: `python scripts/analyze_synthetic_runs.py --out .runtime/<arquivo-novo>.json --seed 20261026`. Não abre coorte piloto, conjunto final ou resultados da outra sessão. O limite de Hoeffding é uma aplicação do [teorema 2 original](https://repository.lib.ncsu.edu/server/api/core/bitstreams/d0e6ed15-3e1c-432f-8419-e55ffb6f3171/content) a somas ponderadas de clusters limitados; a [documentação primária do bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) fundamenta pareamento e degeneração de BCa. A implementação usa somente a biblioteca padrão.

SHA-256: módulo `a122ca60a1e966e2c43245d41cb5e6e5dc8244fd87382bb53807cb7ce398974a`; testes `0dc742b15df6b3aff1acbf4488bb3183e5e1c57dbb10789e036d9f7be2024c79`; CLI `1968086af4433a6c675fd2ab0b1e9b9a5b825b338f03d00931aa188f210b30ec`. Os relatórios privados dos ensaios final e zero têm hashes `51cad935edb66fed59774d4590ab73d4579504d4f9037406f327e185efccf713` e `cceb8bc50e8691d1c596dbf0e9de77d3325278a8524c292d7cd6c73f2bea3c8b`.

O agente distinto `review_c0_data` confrontou a fonte acima com 29 contraprovas matemáticas e três coortes sintéticas para a sequência H1/H3/H2: sem bloqueante. O parecer está na [revisão independente](2026-10-26-c0-dados.md). Limitação preservada: o fallback conservador pode não confirmar não inferioridade mesmo com alta utilidade observada nas duas condições; isso não autoriza recalibrar o método após ver resultados.

Fontes conferidas (SHA-256): `run_record_v4.py` `9d815adff49cc167e36c36c220e50558ac2874170c3b6263cf6958cdba41cf1f`; `terminal_llm_stage.py` `8618292ae28f3bf7c0e00a6f6ac600f117da3be5cc0d14e31661d30ac3137776`; `run_record_store.py` `daef1e7c09a110bdea7d053b1ee3557886b7adde8b81f046726142d862478001`; `dataset_oracle.py` `d72d973f91871a40ca5ab33aa9ada88b56ed79effc20a4c0c87cd43a636902db`.

## Atualização de escopo — 27/10/2026

O parecer acima preserva o escopo e os hashes efetivamente revistos em 26/10. O [estudo descritivo adotado (DEC-094)](../decision-log.md#dec-094) e a [reconciliação corrente (DEC-097)](../decision-log.md#dec-097) substituem as cobranças confirmatórias, o corpus adicional e a proposta antes pendente. Permanecem válidas as provas de componentes, contratos, matemática, segurança e preparo. A coleta vigente tem 144 execuções; revisão do lote, intervalos aplicados e aceite do artigo continuam separados. Não se atribui à revisão antiga cobertura da implementação integrada posterior.

## Integração da análise descritiva — 27/10/2026

O integrador verificou a agenda/identidade do novo runner e os contratos associados em 216 testes focais, todos aprovados (22,11 s, relatório privado `.runtime/pytest-blockers-20261027-final.xml`). A adaptação da análise tem sete contraprovas sintéticas: benignos com `state_violation=false` não diluem o contraste adversarial (−1, não −0,5), UACR usa só adversariais A3a, ausência retira somente o slot pareado, zero uniforme recebe intervalo conservador, ordem/seed são reproduzíveis e a saída corrente não contém testes confirmatórios. A CLI passou com 144 linhas geradas e 10.000 réplicas. A primeira execução focal no ambiente restrito falhou por permissão no temporário; a repetição com acesso local e diretório dedicado passou, sem remover testes.

Os scripts de análise não pertencem ao conjunto monitorado da coleta. Seu inventário foi obtido pelo próprio `PilotStateHarness.source_hashes`: os 158 caminhos/hashes permaneceram idênticos após a mudança. Não foram consultados resultados, alterados insumos ou executadas chamadas/Docker nesta adaptação. Os critérios confirmatórios antigos permanecem temporariamente na API matemática fixada no bundle, sem uso na saída descritiva; sua remoção não justifica interromper o piloto. A ausência de retry integrado da leitura final é uma limitação declarada: captura inválida para o lote, em vez de produzir MISSING artificial. A execução completa, os dados reais e o artigo continuam sujeitos à conferência posterior.
