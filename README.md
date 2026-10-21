# TCC — Arquitetura de proteção na integração de LLMs em ERPs

Este repositório contém o plano-mestre editável do TCC em Ciência da Computação sobre mitigação de prompt injection indireta em um fluxo de Contas a Pagar integrado ao Odoo 19.0 Community self-hosted.

**Comece pela [leitura rápida do experimento](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#leitura-rapida) e pelas [prioridades do grupo](docs/task-backlog.md).** A versão 1.2.20 registra a [ratificação das correções de medição (DEC-063)](docs/decision-log.md#dec-063) e amplia a falha técnica fechada do §10.2. A 1.2.19 aplicou o [corte da entrega (DEC-058)](docs/decision-log.md#dec-058), que mantém DeepSeek, C0/C1, 90 pares/180 documentos, três repetições e 1.080 execuções principais, mais 144 de piloto separado. Qwen3, ablação e ataques adaptados à defesa ficam para trabalho futuro. Overhead e subgrupos serão descritivos; a revisão de literatura será dirigida e transparente. Não houve coleta de resultados finais.

As referências têm descrição e destino: [segurança (RQ1)](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#rq1) é uma pergunta de pesquisa; [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022) é uma decisão histórica. IDs retirados permanecem reservados, não renumerados. Outros termos estão no [glossário do plano](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#glossario).

## Artefatos principais

Estado técnico atual: há [12 pares/24 PDFs candidatos](docs/lab-runbook.md#preparacao-12-pares-piloto), [12 bases comerciais](docs/lab-runbook.md#bases-comerciais-piloto), [oito origens A3a materializadas uma por vez com dezesseis restaurações verificadas (DEC-073)](docs/lab-runbook.md#reset-unitario-a3a) e [cinco bancos alternativos](docs/lab-runbook.md#cadastros-alternativos-piloto). A [relação pedido/produto A1 foi corrigida na candidata `.3` (DEC-071)](docs/lab-runbook.md#correcao-pedido-produto), com zero lacunas no Odoo. O [handoff REVIEW→aprovação→POST privado](docs/lab-runbook.md#handoff-post-observado) passou com provedor simulado. **O piloto ainda depende de aprovação legítima por documento, ciclo integrado e revisão independente.** O reset unitário foi validado tecnicamente, não a comparação C0/C1. DATA-06 e RUN-02 continuam ativas; `execute` público permanece fechado. Os [três bloqueios no backlog](docs/task-backlog.md) distinguem preparação técnica das 144 execuções. O freeze final vem depois do piloto.

- `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md`: fonte editorial e operacional.
- `AGENTS.md`: regras obrigatórias de execução, versionamento, decisões e proteção de dados.
- `CHANGELOG.md`: histórico das versões publicadas do plano-mestre.
- `docs/decision-log.md`: decisões surgidas durante a construção.
- `docs/protocol.md`: protocolo candidato pré-piloto; SCI-01/SCI-03 ainda exigem revisão e assinatura, conforme [DEC-032](docs/decision-log.md#dec-032).
- `docs/deviation-log.md`: divergências depois do congelamento experimental.
- `docs/institutional-requirements.md`: matriz de conformidade com edital, template, calendário e avaliação do TCC II 2026/2.
- `docs/lab-runbook.md`: procedimento operacional dos marcos M1–M2, evidências, recuperação e limites.
- `docs/m2-c0-baseline.md`: relatório técnico, interpretação e limites científicos do vertical slice M2/C0.
- `docs/model-selection.md`: papéis dos modelos, configuração comum, proveniência, segurança e gates de G3 definidos em [seleção dos modelos (DEC-018)](docs/decision-log.md#dec-018).
- `docs/llm-egress-and-adapters.md`: fronteira mínima de rede, ameaças, contrato comum e gates dos adapters definidos em [isolamento da chamada ao modelo (DEC-020)](docs/decision-log.md#dec-020).
- `docs/g3a-llm-adapters.md`: evidência técnica saneada da implementação simulada e dos 82 testes de G3a.
- `docs/g3b-egress-topology.md`: evidência da API interna, topologia executável, proxy allowlisted e testes negativos offline de G3b.
- `docs/revisao-independente-v1.2.9.md`: dossiê da revisão adversarial em doze dimensões, com 120 achados verificados, evidência literal, veredito e correção recomendada, conforme [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022).
- `docs/task-backlog.md`: prioridades e três trilhas paralelas, com os 123 IDs preservados, donos, revisores, dependências e DoD; blocos retirados têm estado `CUT`, não `DONE`.
- `dataset/codebook.md`: contrato candidato dos pares, taxonomia, ligação com fixtures e gates de revisão; ainda não é dataset piloto/final.
- `paper/`: fonte LaTeX editável, referências, validação e PDF pré-experimental do artigo institucional do TCC II, conforme [fonte do artigo (DEC-019)](docs/decision-log.md#dec-019).
- `docs/releases/v1.2.20.md`: manifesto da versão corrente; versões anteriores permanecem em `docs/releases/` para auditoria, sem fazer parte do roteiro de leitura.
- `reproducibility/odoo-source.lock.json`: lock legível por máquina da fonte Odoo selecionada.
- `reproducibility/lab-environment.lock.json`: versões, digests e últimos aceites M1/M2 saneados do laboratório.
- `reproducibility/model-selection.lock.json`: seleção histórica dos modelos, escopo atual somente DeepSeek e evidências pendentes para o freeze.
- `reproducibility/institutional-sources.lock.json`: hashes, requisitos e anomalias das fontes institucionais locais.
- `reproducibility/institutional-evidence.lock.json`: hashes e conclusões saneadas de evidências institucionais privadas mantidas fora do Git.
- `scripts/check_repository_safety.ps1`: verificação de caminhos proibidos e padrões de credenciais sem exibir o valor suspeito.
- `scripts/validate_current_docs.py`: validação corrente do Markdown, links, escopo e referências do artigo.
- `odoo-19.0/`: snapshot local ignorado pelo Git e usado somente para exploração; o build usa a origem oficial no commit fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`, e o manifest OCI aceito está registrado nos locks.
- `relatorio_tcc_I_fci_pacote/`: pacote local ignorado, usado somente como evidência de continuidade e referência institucional; contém repositório aninhado e dados acadêmicos que não devem ser preparados para commit.

## Estado executável

O marco M1 foi validado em 31/08/2026, ainda antes do congelamento experimental. O laboratório constrói Odoo 19.0 Community a partir do commit fixado, sobe PostgreSQL 18 em rede interna, usa uma identidade C0 dedicada e executa por JSON-2 a criação e a remoção de exatamente uma conta de fornecedor sintética em rascunho. A conta mantém a referência bancária e a ligação com a linha de um pedido de compra confirmado; o hash canônico após a remoção coincide com o estado inicial.

O marco M2 também foi validado em 31/08/2026. Ele gera localmente um PDF sintético benigno com camada de texto, extrai o conteúdo sem OCR, produz uma proposta tipada validada por JSON Schema, resolve as referências por chaves de negócio e cria o mesmo rascunho via executor direto C0. Foram aprovados 41 testes e o hash após a remoção voltou ao estado inicial.

M2 é uma baseline de desenvolvimento do encanamento, não o C0 científico: o adaptador `deterministic-development/v1` não usa LLM e está proibido nas runs experimentais. Esses aceites M1/M2 não incluem modelo LLM, prompt injection, C1, add-on de autorização, postagem ou pagamento; os checkpoints posteriores têm provas próprias. O manifesto OCI é local e não foi publicado em registry. O estado verificável corrente está em `reproducibility/lab-environment.lock.json`; PDF, credenciais e evidências detalhadas permanecem em `.runtime`, fora do Git.

Os modelos de G3 foram selecionados na [DEC-018](docs/decision-log.md#dec-018); a [DEC-058](docs/decision-log.md#dec-058) mantém somente DeepSeek na entrega. O piloto solicita `model=deepseek-flash` conforme o [pacote pré-piloto (DEC-029)](docs/decision-log.md#dec-029), igual em C0/C1, com *thinking* desligado. O alias legado e seu backend documentado permanecem evidência histórica, não garantia atual de snapshot imutável. O backend deve ser registrado por execução e conferido antes da coleta. G3a/G3b, o [smoke canônico (DEC-030)](docs/decision-log.md#dec-030), os estágios offline e as provas privadas do contrato v2 têm seus aceites técnicos próprios; não demonstram competência C0, eficácia C1 ou prontidão científica. Integração operacional, supervisão e revisão continuam pendentes.

Qwen3 não exige download, benchmark ou smoke nesta entrega. Seus contratos e registros históricos não serão apagados. A rede do laboratório permanece interna e a chave DeepSeek continua em arquivo local ignorado, acessível somente ao cliente no profile real, sem versionamento.

Os três workstreams foram atribuídos em [divisão do trabalho (DEC-021)](docs/decision-log.md#dec-021): Felipe lidera ciência e dados, Thomaz lidera arquitetura e segurança, e Gustavo lidera Odoo e experimentação. Todas as pendências conhecidas estão identificadas em `docs/task-backlog.md`, com responsáveis, revisores, dependências e critérios objetivos de conclusão para permitir execução paralela sem perder os pontos de integração.

## Execução local de M1 e M2

Pré-requisitos: PowerShell, Git, Docker Desktop em modo Linux/AMD64, Docker Compose e acesso de rede no primeiro build.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1
```

O primeiro comando gera credenciais locais aleatórias sem exibi-las. O segundo revalida M1, cria um builder isolado, exporta a mesma resolução em formatos OCI e Docker, verifica manifest, config, labels e commit interno, executa 41 testes, carrega as fixtures sintéticas e roda os smokes M1/M2. Ao terminar, os contêineres são encerrados e os volumes são preservados. Para executar somente M1, use `scripts/smoke_test.ps1`.

Não use `new_local_env.ps1 -Force` com um banco existente sem planejar a rotação conjunta do volume. A opção `smoke_test.ps1 -RecreateVolumes` remove somente os volumes rotulados do projeto, mas é destrutiva e exige autorização explícita do operador. O procedimento completo e os critérios de diagnóstico estão em `docs/lab-runbook.md`.

## Artigo institucional do TCC II

O artigo separado está em `paper/`. A compilação de 17/10/2026 tem 18 páginas e passou pelas verificações de extensão, Resumo/Abstract (213/189 palavras), estrutura, 20 citações/referências, metadados e inspeção visual. Distingue M1/M2 históricos dos incrementos técnicos privados posteriores, sem apresentar eficácia medida. Integração/revisão, piloto, freeze e coleta continuam pendentes: é versão para revisão, não arquivo final de submissão.

## Edição do plano

O plano-mestre é mantido somente em Markdown. Não há etapa de conversão para Word ou PDF. O artigo institucional é produzido separadamente em `paper/`, com fonte e validação próprias.

## Segurança e publicação de versões

Antes de preparar qualquer commit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
```

Depois de adicionar somente os caminhos pretendidos, executar novamente com `-StagedOnly`. Arquivos `.env`, `.runtime`, chaves, tokens, dumps, dados reais, logs brutos, exports locais de imagem e o snapshot local do Odoo não podem ser versionados. Cada versão publicada do plano corresponde a um commit dedicado com o Markdown, decisões, changelog e manifesto; o procedimento completo está em `AGENTS.md`.

Os dados brutos dos experimentos permanecem fora do Git em armazenamento criptografado e com cópia imutável. O repositório deve conter somente o manifesto saneado de hashes, schema, proveniência e retenção, além dos exports sintéticos aprovados para publicação.

O documento é um plano de execução, não o artigo final. O edital e o template de 2026/2 já foram auditados: o produto institucional será um artigo separado de 10–20 páginas, submetido inicialmente no Oriente entre 03 e 09/11/2026. As lacunas residuais estão listadas em `docs/institutional-requirements.md`.
