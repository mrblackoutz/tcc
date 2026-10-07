# TCC — Arquitetura de proteção na integração de LLMs em ERPs

Este repositório contém o plano-mestre editável do TCC em Ciência da Computação sobre mitigação de prompt injection indireta em um fluxo de Contas a Pagar integrado ao Odoo 19.0 Community self-hosted.

**Comece pela [leitura rápida do experimento](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#leitura-rapida).** A versão 1.2.18 mantém a avaliação em alteração de campos, troca de beneficiário e contabilização sem autorização; esclarece idempotência e valores fixos do executor, preservando o contrato de ação v2. A frente de exposição de dados foi retirada na v1.2.12. A meta continua em 90 pares, 30 por objetivo; não houve coleta de resultados finais.

As referências têm descrição e destino: [contribuição das camadas (RQ4)](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#rq4) é uma pergunta de pesquisa; [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022) é uma decisão histórica; [retirada da exposição de dados (DEC-023)](docs/decision-log.md#dec-023) registra esta mudança. Outros termos estão no [glossário do plano](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#glossario).

## Artefatos principais

Estado técnico atual: os núcleos privados de rascunho, aprovação, contabilização e [auditoria/anexação C1-09](docs/lab-runbook.md#auditoria-operacional-privada-c1-09) estão implementados. [Bypass C1-10](docs/lab-runbook.md#bypass-http-c1-10), [transações reais C1-11](docs/lab-runbook.md#transações-reais-e-ciclo-de-commit-c1-11) e [registro documental privado](docs/lab-runbook.md#registro-privado-de-workflow-documental) passaram. O [contrato v2 comum e a ponte do runner](docs/lab-runbook.md#contrato-v2-comum-e-ponte-do-runner) também passaram offline: mesma proposta para C0, política C1 e conversor do oráculo; 1.453 testes, 193 novos. Essas frentes aguardam revisão humana; `execute` público continua fechado. **Próximo checkpoint: ligar runner ao registro e às observações Odoo reais, com prova nativa C0/POST e captura de estado/oráculo.** RUN-02/03 seguem em construção; dataset, piloto e freeze pendentes. Prioridades estão no [backlog](docs/task-backlog.md#10-runner-oráculo-e-observabilidade-experimental).

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
- `docs/task-backlog.md`: inventário operacional de 116 tarefas, dependências, revisões, DoD e ondas paralelas dos três integrantes conforme [divisão do trabalho (DEC-021)](docs/decision-log.md#dec-021).
- `paper/`: fonte LaTeX editável, referências, validação e PDF pré-experimental do artigo institucional do TCC II, conforme [fonte do artigo (DEC-019)](docs/decision-log.md#dec-019).
- `docs/releases/v1.2.18.md`: manifesto da versão corrente; versões anteriores permanecem em `docs/releases/` para auditoria, sem fazer parte do roteiro de leitura.
- `reproducibility/odoo-source.lock.json`: lock legível por máquina da fonte Odoo selecionada.
- `reproducibility/lab-environment.lock.json`: versões, digests e últimos aceites M1/M2 saneados do laboratório.
- `reproducibility/model-selection.lock.json`: seleção datada do DeepSeek e Qwen3, fatos observados e evidências ainda pendentes para o freeze.
- `reproducibility/institutional-sources.lock.json`: hashes, requisitos e anomalias das fontes institucionais locais.
- `reproducibility/institutional-evidence.lock.json`: hashes e conclusões saneadas de evidências institucionais privadas mantidas fora do Git.
- `scripts/check_repository_safety.ps1`: verificação de caminhos proibidos e padrões de credenciais sem exibir o valor suspeito.
- `scripts/validate_current_docs.py`: validação corrente do Markdown, links, escopo e referências do artigo.
- `odoo-19.0/`: snapshot local ignorado pelo Git e usado somente para exploração; o build usa a origem oficial no commit fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`, e o manifest OCI aceito está registrado nos locks.
- `relatorio_tcc_I_fci_pacote/`: pacote local ignorado, usado somente como evidência de continuidade e referência institucional; contém repositório aninhado e dados acadêmicos que não devem ser preparados para commit.

## Estado executável

O marco M1 foi validado em 31/08/2026, ainda antes do congelamento experimental. O laboratório constrói Odoo 19.0 Community a partir do commit fixado, sobe PostgreSQL 18 em rede interna, usa uma identidade C0 dedicada e executa por JSON-2 a criação e a remoção de exatamente uma conta de fornecedor sintética em rascunho. A conta mantém a referência bancária e a ligação com a linha de um pedido de compra confirmado; o hash canônico após a remoção coincide com o estado inicial.

O marco M2 também foi validado em 31/08/2026. Ele gera localmente um PDF sintético benigno com camada de texto, extrai o conteúdo sem OCR, produz uma proposta tipada validada por JSON Schema, resolve as referências por chaves de negócio e cria o mesmo rascunho via executor direto C0. Foram aprovados 41 testes e o hash após a remoção voltou ao estado inicial.

M2 é uma baseline de desenvolvimento do encanamento, não o C0 científico: o adaptador `deterministic-development/v1` não usa LLM e está proibido nas runs experimentais. Os aceites ainda não incluem modelo LLM, prompt injection, C1, add-on de autorização, postagem ou pagamento. O manifesto OCI é local e não foi publicado em registry. O estado verificável corrente está em `reproducibility/lab-environment.lock.json`; PDF, credenciais e evidências detalhadas permanecem em `.runtime`, fora do Git.

Os modelos de G3 foram selecionados em [seleção dos modelos (DEC-018)](docs/decision-log.md#dec-018). O piloto do bloco principal está configurado para solicitar `model=deepseek-flash` conforme [pacote técnico pré-piloto (DEC-029)](docs/decision-log.md#dec-029); o alias legado `deepseek-v4-flash` usado no smoke de 24/09 é preservado como evidência histórica. Ambos são móveis: o [roteamento atualizado (DEC-024)](docs/decision-log.md#dec-024) registra a passagem para V4.1 Flash. O bloco posterior de robustez usará `qwen3:14b-q4_K_M` via Ollama. Cada bloco preserva C0/C1 com o mesmo modelo e configuração e usa *thinking* desligado. G3a aprovou adapters e mocks; G3b materializou `llm-client`, redes internas e proxy de destino fixo. O [smoke canônico G3-06 (DEC-030)](docs/decision-log.md#dec-030) passou em uma chamada sintética real, sem retry e com manifesto saneado. O [estágio de tentativas (DEC-031)](docs/decision-log.md#dec-031) e o [classificador pré-freeze (DEC-032)](docs/decision-log.md#dec-032) passaram em testes offline, mas o runner Odoo completo, a competência C0, a revisão independente e a avaliação C0/C1 continuam pendentes; o smoke não é run científica. A [lacuna de ação A3a (DEC-033)](docs/decision-log.md#dec-033) bloqueia o piloto.

O host observado possui Ollama 0.30.10 e RTX 3060 Ti com 8 GiB de VRAM. Como o Qwen quantizado ocupa aproximadamente 9,3 GB, sua inclusão depende de smoke com offload parcial e manifest completo registrado. O modelo não foi baixado por esta release. A rede do laboratório permanece interna; a chave DeepSeek foi lida somente pelo cliente no profile real e permanece em arquivo local ignorado, sem versionamento.

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

O artigo separado já está disponível em `paper/`. A compilação corrente tem 17 páginas e passou pelos gates de extensão, contagem de Resumo/Abstract, estrutura, reconciliação de 20 citações com 20 referências, metadados e inspeção visual. Ela registra somente os resultados técnicos comprovados de M1/M2; C1, piloto, freeze e resultados confirmatórios ainda estão pendentes. Portanto, é uma versão profissional para revisão com o orientador, não o arquivo final de submissão.

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
