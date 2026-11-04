# Arquitetura de proteção na integração de LLMs em ERPs

Trabalho de Conclusão de Curso II em Ciência da Computação, Faculdade de Computação e Informática da Universidade Presbiteriana Mackenzie, 2º semestre de 2026.

- **Autores:** Felipe Ujvari Gasparino de Sousa, Gustavo Nascimento Siqueira e Thomaz de Souza Scopel.
- **Orientador:** Mario Olimpio de Menezes.

**Artefato principal: o [artigo](paper/relatorio_tcc_ii.pdf)** (PDF, 19 páginas). É a versão em avaliação pelo orientador; a fonte LaTeX está em [`paper/`](paper/README.md).

## Em resumo

- **Problema:** um agente baseado em modelo de linguagem (LLM) que lê faturas em PDF e prepara lançamentos de Contas a Pagar pode ser enganado por texto escondido no próprio documento, a chamada *prompt injection* indireta. O ataque pode alterar valores, trocar a conta bancária do fornecedor ou contabilizar sem autorização.
- **O que foi construído:** duas formas de ligar o modelo ao Odoo 19.0 Community.
  - **C0 (versão simples):** o que o modelo propõe vai direto ao Odoo pela API JSON-2.
  - **C1 (versão protegida):** uma política determinística confere a proposta com dados confiáveis, contabilizar exige aprovação vinculada à ação, e só um add-on com menor privilégio altera o Odoo, com idempotência e auditoria.
- **Como foi avaliado:** 12 pares de faturas sintéticas sem valor fiscal (em cada par, uma normal e uma com ataque) × 2 versões × 3 repetições = 144 execuções reais no Odoo, em 27/10/2026, com o modelo DeepSeek (`deepseek-flash`) chamado dentro de cada execução.
- **O que deu:**
  - nenhum ataque funcionou, em nenhuma das versões (0/36 em cada);
  - nenhuma contabilização foi feita sem autorização (0/12 em cada);
  - as tarefas normais foram concluídas em 36/36 em C0 e 35/36 em C1. A perda em C1 veio de uma resposta do modelo fora do formato exigido, com pedido idêntico ao de C0, e não de um bloqueio da defesa.
- **O que isso significa:** como o modelo não seguiu nenhuma injeção, a defesa não chegou a ser posta à prova. O estudo é descritivo: mostra o comportamento das duas versões, o custo extra de C1 e o funcionamento da aprovação, mas **não demonstra redução de ataques**. A amostra é pequena e há um único modelo.

## Onde está cada coisa

| Para ver | Onde |
|---|---|
| O artigo e sua fonte | [`paper/relatorio_tcc_ii.pdf`](paper/relatorio_tcc_ii.pdf) e [`paper/`](paper/README.md) |
| Resultado da execução, com denominadores, tempos e custo | [resultado do piloto no Odoo](docs/pilot-state-resultado.md) |
| Configuração exata testada, com hashes | [configuração avaliada](docs/configuracao-avaliada.md) |
| Revisões feitas | [`docs/reviews/`](docs/reviews/) |
| Decisões tomadas ao longo do trabalho | [registro de decisões](docs/decision-log.md); identificadores de commit anteriores a 04/11/2026 correspondem aos atuais pelo [mapa de commits](reproducibility/commit-map-2026-11-04.json) |
| Uso de IA no trabalho | [registro de uso de IA](docs/ai-usage.md) e [respostas da declaração institucional](docs/declaracao-ia-respostas.md) |
| Política e executor da versão protegida | [`gateway/src/tcc_gateway/`](gateway/src/tcc_gateway/) e [`odoo/addons/ap_security_executor/`](odoo/addons/ap_security_executor/) |
| Execução do experimento | [`scripts/pilot_state_harness.py`](scripts/pilot_state_harness.py) e [runbook do laboratório](docs/lab-runbook.md#piloto-estado-odoo) |
| Plano de pesquisa completo | [plano-mestre](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md) |

## Como conferir e reproduzir

- **O artigo:** `scripts/validate_current_docs.py` e `paper/validate_paper.ps1` conferem páginas, resumos, títulos, citações e metadados. Os resultados e hashes da compilação corrente estão em [`paper/validation-report.json`](paper/validation-report.json).
- **Os números:** o [resultado do piloto](docs/pilot-state-resultado.md) traz o comando da análise e confere tokens e chamadas com o extrato de uso do provedor. Os registros brutos de cada execução ficam fora do repositório (ver abaixo); aqui estão os hashes que permitem verificá-los.
- **O laboratório:** roda em Docker, com o Odoo construído a partir do commit fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`. Os passos estão no [runbook](docs/lab-runbook.md) e na seção "Execução local de M1 e M2", abaixo.
- **Repetir as execuções:** exige uma chave própria da API DeepSeek. Como o nome `deepseek-flash` aponta para um modelo que o provedor pode trocar, uma nova execução não reproduz bit a bit a anterior.

## Dados, privacidade e uso de IA

- **Dados sintéticos:** todos os documentos são sintéticos e marcados como sem valor fiscal. Não há dados reais nem participantes humanos.
- **Dados brutos fora do Git:** registros, capturas do Odoo e logs ficam fora do repositório, com cópia local cifrada e restauração conferida. Essa cópia fica no mesmo computador; não é cópia externa nem imutável.
- **Segredos:** chaves e senhas nunca são versionadas. O [`.env.example`](.env.example) tem só nomes de variáveis e valores fictícios.
- **Uso de IA:** o trabalho usou assistentes de IA em quase todas as etapas, como descrito no [registro de uso de IA](docs/ai-usage.md). A declaração institucional assinada (Anexo I) vai anexada ao PDF de submissão. Esse PDF fica fora do repositório porque a declaração traz identificadores acadêmicos.

## Para quem trabalha no repositório

As regras obrigatórias de execução, versionamento, decisões e proteção de dados estão em [`AGENTS.md`](AGENTS.md). O andamento e os responsáveis estão no [backlog](docs/task-backlog.md).

As referências do tipo [segurança (RQ1)](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#rq1) apontam para perguntas de pesquisa; as do tipo [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022), para decisões históricas. IDs retirados permanecem reservados e não são renumerados. Outros termos estão no [glossário do plano](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#glossario).

**Histórico do escopo:**

- A versão 1.2.21 do plano registra a [decisão de 26/10 (DEC-094)](docs/decision-log.md#dec-094): como nenhum ataque funcionou na versão simples no estágio de propostas, o estudo passou a descritivo e o piloto de 144 execuções no Odoo virou a avaliação. O conjunto de 90 pares e 1.080 execuções ficou para trabalho futuro.
- A versão 1.2.20 registrou a [ratificação das correções de medição (DEC-063)](docs/decision-log.md#dec-063).
- A versão 1.2.19 aplicou o [corte da entrega (DEC-058)](docs/decision-log.md#dec-058).
- Qwen3, ablação e ataques adaptados à defesa ficam para trabalho futuro.

### Mapa dos arquivos

- `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md`: fonte editorial e operacional do plano de pesquisa.
- `AGENTS.md`: regras obrigatórias de execução, versionamento, decisões e proteção de dados.
- `CHANGELOG.md`: histórico das versões publicadas do plano-mestre.
- `docs/decision-log.md`: decisões surgidas durante a construção.
- `docs/protocol.md`: protocolo vigente da avaliação descritiva, com denominadores, falhas, intervalos e limites de aceite.
- `docs/deviation-log.md`: divergências depois do congelamento experimental.
- `docs/pilot-state-resultado.md`: resultado das 144 execuções no Odoo.
- `docs/configuracao-avaliada.md`: configuração exata da execução avaliada.
- `docs/institutional-requirements.md`: matriz de conformidade com edital, template, calendário e avaliação do TCC II 2026/2.
- `docs/lab-runbook.md`: procedimento operacional do laboratório, evidências, recuperação e limites.
- `docs/m2-c0-baseline.md`: relatório técnico, interpretação e limites científicos do vertical slice M2/C0.
- `docs/model-selection.md`: papéis dos modelos, configuração comum, proveniência, segurança e gates de G3 definidos em [seleção dos modelos (DEC-018)](docs/decision-log.md#dec-018).
- `docs/llm-egress-and-adapters.md`: fronteira mínima de rede, ameaças, contrato comum e gates dos adapters definidos em [isolamento da chamada ao modelo (DEC-020)](docs/decision-log.md#dec-020).
- `docs/g3a-llm-adapters.md`: evidência técnica saneada da implementação simulada e dos 82 testes de G3a.
- `docs/g3b-egress-topology.md`: evidência da API interna, topologia executável, proxy allowlisted e testes negativos offline de G3b.
- `docs/revisao-independente-v1.2.9.md`: dossiê da revisão adversarial em doze dimensões, com 120 achados verificados, conforme [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022).
- `docs/task-backlog.md`: prioridades, donos, revisores, dependências e critérios de conclusão; blocos retirados têm estado `CUT`, não `DONE`.
- `docs/ai-usage.md` e `docs/declaracao-ia-respostas.md`: registro de uso de IA e respostas da declaração institucional.
- `dataset/codebook.md`: contrato dos pares, taxonomia, ligação com fixtures e gates de revisão.
- `paper/`: fonte LaTeX, referências, validação e PDF do artigo institucional do TCC II, conforme [fonte do artigo (DEC-019)](docs/decision-log.md#dec-019).
- `docs/releases/v1.2.21.md`: manifesto da versão corrente do plano; versões anteriores permanecem em `docs/releases/` para auditoria.
- `reproducibility/odoo-source.lock.json`: lock legível por máquina da fonte Odoo e do manifest OCI aceito.
- `reproducibility/lab-environment.lock.json`: versões, digests e últimos aceites M1/M2 saneados do laboratório.
- `reproducibility/model-selection.lock.json`: seleção histórica dos modelos e escopo atual somente DeepSeek.
- `reproducibility/institutional-sources.lock.json`: hashes, requisitos e anomalias das fontes institucionais locais.
- `reproducibility/institutional-evidence.lock.json`: hashes e conclusões saneadas de evidências institucionais privadas mantidas fora do Git.
- `scripts/check_repository_safety.ps1`: verificação de caminhos proibidos e padrões de credenciais sem exibir o valor suspeito.
- `scripts/validate_current_docs.py`: validação corrente do Markdown, links, escopo e referências do artigo.
- `odoo-19.0/` e `relatorio_tcc_I_fci_pacote/`: pastas locais ignoradas pelo Git, usadas só para exploração e como evidência de continuidade.

## Estado executável

O marco M1 foi validado em 31/08/2026. O laboratório constrói o Odoo 19.0 Community a partir do commit fixado, sobe o PostgreSQL 18 em rede interna, usa uma identidade C0 dedicada e executa por JSON-2 a criação e a remoção de uma conta de fornecedor sintética em rascunho. O hash canônico após a remoção coincide com o estado inicial.

O marco M2 também foi validado em 31/08/2026. Ele gera um PDF sintético com camada de texto, extrai o conteúdo sem OCR, produz uma proposta tipada validada por JSON Schema, resolve as referências por chaves de negócio e cria o mesmo rascunho via executor direto C0. M2 é uma baseline de desenvolvimento do encanamento, não o C0 científico: o adaptador `deterministic-development/v1` não usa LLM e está proibido nas execuções experimentais.

O piloto solicita `model=deepseek-flash`, igual em C0 e C1, com *thinking* desligado, conforme o [pacote pré-piloto (DEC-029)](docs/decision-log.md#dec-029). O nome devolvido pelo provedor é registrado em cada execução. A execução integrada das [DEC-095 e DEC-096](docs/decision-log.md#dec-096) terminou com 144/144 execuções válidas e passou na [revisão independente](docs/reviews/2026-10-27-piloto-concluido.md). A rede do laboratório é interna e a chave DeepSeek fica num arquivo local ignorado, acessível só ao cliente do modelo.

Os três workstreams foram atribuídos em [divisão do trabalho (DEC-021)](docs/decision-log.md#dec-021): Felipe lidera ciência e dados, Thomaz lidera arquitetura e segurança, e Gustavo lidera Odoo e experimentação.

## Execução local de M1 e M2

Pré-requisitos: PowerShell, Git, Docker Desktop em modo Linux/AMD64, Docker Compose e acesso de rede no primeiro build.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1
```

O primeiro comando gera credenciais locais aleatórias sem exibi-las. O segundo revalida M1, cria um builder isolado, exporta a mesma resolução em formatos OCI e Docker, verifica manifest, config, labels e commit interno, executa 41 testes, carrega as fixtures sintéticas e roda os smokes M1/M2. Ao terminar, os contêineres são encerrados e os volumes são preservados. Para executar somente M1, use `scripts/smoke_test.ps1`.

Não use `new_local_env.ps1 -Force` com um banco existente sem planejar a rotação conjunta do volume. A opção `smoke_test.ps1 -RecreateVolumes` remove somente os volumes rotulados do projeto, mas é destrutiva e exige autorização explícita do operador. O procedimento completo e os critérios de diagnóstico estão em `docs/lab-runbook.md`.

## Artigo institucional do TCC II

O artigo está em `paper/`. A compilação de 04/11/2026 tem 19 páginas, Resumo de 244 palavras e Abstract de 234, 20 citações para 20 referências, e passou nas verificações automáticas e na inspeção visual. O PDF de submissão acrescenta ao fim a declaração de uso de IA assinada, que não conta nas 20 páginas; ele é gerado por `paper/build_submission.sh` e fica fora do Git. Detalhes em [`paper/README.md`](paper/README.md).

## Segurança e publicação de versões

Antes de preparar qualquer commit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
```

Depois de adicionar somente os caminhos pretendidos, executar novamente com `-StagedOnly`. Arquivos `.env`, `.runtime`, chaves, tokens, dumps, dados reais, logs brutos, exports locais de imagem e o snapshot local do Odoo não podem ser versionados. Cada versão publicada do plano corresponde a um commit dedicado com o Markdown, decisões, changelog e manifesto; o procedimento completo está em `AGENTS.md`.

O plano-mestre é mantido somente em Markdown, sem conversão para Word ou PDF. O artigo institucional é produzido separadamente em `paper/`, com fonte e validação próprias.
