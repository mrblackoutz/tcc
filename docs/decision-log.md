# Registro de decisões

Este log complementa as decisões D01–D15 do plano-mestre. Nenhuma decisão material deve permanecer apenas em conversa, memória individual ou código.

## Modelo obrigatório

```text
ID:
Data:
Status: proposta | aceita | substituída | rejeitada
Contexto:
Alternativas consideradas:
Decisão:
Consequências e trade-offs:
Evidência necessária ou disponível:
Responsável pela decisão:
Seções, código, dados e runs afetados:
Substitui ou é substituída por:
```

## DEC-001 — Caso de uso e ameaça principal

- **Data:** 26/08/2026
- **Status:** aceita
- **Contexto:** a agenda anterior era ampla e sem artefato empírico.
- **Alternativas consideradas:** múltiplos processos corporativos; estoque; atendimento; Contas a Pagar.
- **Decisão:** restringir o estudo a documentos sintéticos de Contas a Pagar, prompt injection indireta e estado observável no Odoo.
- **Consequências:** maior validade interna e escopo executável; generalização limitada a outros processos.
- **Evidência:** decisões D01–D04 e seções 3–8 do plano 1.2.
- **Responsável:** grupo, sujeito à validação do orientador.
- **Afeta:** problema, RQs, dataset, threat model, arquitetura e experimento.

## DEC-002 — Ambiente Odoo

- **Data:** 29/08/2026
- **Status:** aceita
- **Contexto:** a documentação `saas-19.4` não representa uma release Community self-hosted suportada.
- **Alternativas consideradas:** Odoo SaaS 19.4; snapshot `saas-19.4`; Odoo 19.0 Community.
- **Decisão:** usar Odoo 19.0 Community self-hosted; excluir SaaS 19.4, Enterprise e IA nativa.
- **Consequências:** ambiente reproduzível e extensível; LLM e controles ficam no gateway externo.
- **Evidência:** D11, W01–W02 e inspeção do snapshot local; nesta decisão, commit/checksum upstream ainda deveria ser congelado.
- **Responsável:** grupo.
- **Afeta:** stack, containers, integração, referências e reprodução.
- **Complementada por:** DEC-009, em 30/08/2026, que fixa o repositório e a revisão de fonte.

## DEC-003 — Fronteira de autorização de C1

- **Data:** 29/08/2026
- **Status:** aceita
- **Contexto:** JSON-2 expõe métodos públicos permitidos ao usuário e aceita contexto do cliente; ACLs padrão de faturamento são amplas.
- **Alternativas consideradas:** CRUD direto por JSON-2; controller customizado; método estreito em add-on chamado por JSON-2.
- **Decisão:** usar JSON-2 como transporte e `ap_security_executor` como fronteira transacional, idempotente e tipada de C1, com usuário técnico restrito.
- **Consequências:** exige add-on mínimo e testes de bypass; interface visual permanece opcional.
- **Evidência:** D12 e §§16.5–16.8 do plano 1.2.
- **Responsável:** grupo.
- **Afeta:** C1, ACLs, executor, testes, protocolo e threat model.

## DEC-004 — Controle do modelo e utilidade

- **Data:** 29/08/2026
- **Status:** aceita
- **Contexto:** trocar modelo entre C0 e C1 confundiria efeito do modelo com efeito da arquitetura.
- **Alternativas consideradas:** modelos diferentes por condição; múltiplos modelos no núcleo; um modelo primário fixo e segundo opcional.
- **Decisão:** usar exatamente o mesmo modelo/configuração em C0 e C1; manter 180 documentos como meta pré-piloto; tratar 10 pontos percentuais de BTSR como margem candidata.
- **Consequências:** seleção do modelo e justificativa da margem devem ocorrer antes do freeze e sem consultar o teste final.
- **Evidência:** W04–W06, H3 e §§14–15 do plano 1.2.
- **Responsável:** grupo; na decisão original, a aprovação final da margem ainda era atribuída ao orientador.
- **Afeta:** piloto, manifesto, poder, custo e análise estatística.
- **Substituída por:** DEC-008 exclusivamente quanto ao caráter candidato e à aprovação da margem; modelo concreto e tamanho amostral final continuam dependentes do piloto em W04 e W05.

## DEC-005 — Governança do histórico e dos segredos

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** decisões dispersas e commits amplos aumentam retrabalho, perda de contexto e risco de vazamento.
- **Alternativas consideradas:** histórico apenas no documento; commits ad hoc; commit dedicado por versão com logs e varredura.
- **Decisão:** publicar cada versão do plano em commit dedicado; registrar decisões/desvios; preparar arquivos explicitamente; bloquear segredos, dados reais, dumps, logs brutos e snapshot local do Odoo.
- **Consequências:** pequena disciplina adicional em troca de rastreabilidade, segurança e capacidade de auditoria.
- **Evidência:** política do plano 1.2, `AGENTS.md`, `.gitignore` e script de segurança.
- **Responsável:** grupo.
- **Afeta:** todos os commits, documentação, dados e releases do plano.

## DEC-006 — Saneamento de artefatos e custódia dos dados brutos

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** DOCX gerado localmente pode herdar identidade do perfil do Word; dados brutos são necessários à auditabilidade, mas podem conter material operacional impróprio para um repositório remoto.
- **Alternativas consideradas:** versionar todos os binários e runs; descartar dados brutos depois da análise; sanear artefatos e preservar dados brutos fora do Git com manifesto verificável.
- **Decisão:** reprovar DOCX com metadados pessoais, comentários, revisões, macros, objetos incorporados ou relações externas inesperadas; manter os dados brutos fora do Git em armazenamento criptografado e imutável, vinculados a manifesto de hashes, schema, proveniência e retenção.
- **Consequências:** a release exige um gate adicional e a reprodução depende da custódia documentada; reduz-se o risco de vazamento sem perder a cadeia de evidências.
- **Evidência:** validação do pacote DOCX, relatório do verificador do repositório e manifesto experimental.
- **Responsável:** grupo.
- **Afeta:** geração e validação de artefatos, publicação de datasets, execução experimental e pacote de reprodução.

## DEC-007 — Âncora da release 1.2 sem reescrita do histórico publicado

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** durante a janela de geração final, os commits `81b8191` e `39baf53` foram criados e enviados a `origin/main` por um processo externo a este fluxo, com mensagens fora do padrão de release. O reflog registra `update by push`; reescrevê-los violaria a política já adotada e poderia apagar trabalho compartilhado.
- **Alternativas consideradas:** amend/rebase e force-push; criar versão 1.2.1 sem mudança científica; preservar os commits e criar uma âncora auditável da mesma v1.2.
- **Decisão:** não reescrever nem remover os commits publicados; criar `docs/releases/v1.2.md` com hashes, gates e a exceção histórica e versioná-lo em commit local dedicado no padrão `docs(plan): release v1.2 — ancora auditavel`.
- **Consequências:** o histórico permanece íntegro e a v1.2 ganha um ponto de auditoria explícito; os dois commits anteriores continuam visíveis como preparação/correção. O commit-âncora não será enviado ao remoto sem autorização do usuário.
- **Evidência:** reflog de `origin/main`, commits `81b8191` e `39baf53`, manifesto da release e resultados de validação.
- **Responsável:** grupo.
- **Afeta:** histórico Git, changelog, política de releases e publicação remota.

## DEC-008 — Confirmação da margem W06

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** na v1.2, a margem de 10 pontos percentuais para a BTSR ainda estava registrada como candidata, embora a hipótese H3 já usasse `−0,10`.
- **Alternativas consideradas:** manter a margem indefinida até o piloto; escolher uma margem depois de observar resultados; confirmar `−0,10` antes do piloto e preservar o valor.
- **Decisão:** confirmar `−0,10` como margem de não inferioridade de `BTSR_C1 − BTSR_C0` e promover a decisão a D13.
- **Consequências:** C1 só será não inferior se o limite inferior do IC95% ficar estritamente acima de `−0,10`; o piloto pode informar precisão, poder e tamanho amostral, mas não alterar a margem com base nos resultados.
- **Evidência:** confirmação do grupo em 30/08/2026, D13, W06, H3 e §15.3 do plano 1.2.1.
- **Responsável:** grupo.
- **Afeta:** hipótese H3, piloto, plano estatístico, freeze, análise e critérios de sucesso.
- **Substitui:** estado provisório de W06 na versão 1.2.

## DEC-009 — Pin imutável da fonte Odoo 19.0

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** a pasta local não possui metadados Git próprios e o branch oficial `19.0` é móvel. O grupo indicou e selecionou `a4b877245c9cb5e3d7152d1593a518170f115ca1`; ele também foi observado na consulta realizada durante a seleção. Uma consulta independente posterior retornou `49baa7f91e6213bddc6f15044ca3c8a4ff79dee5`, um commit à frente.
- **Alternativas consideradas:** seguir automaticamente o HEAD do branch; escolher o HEAD somente no freeze; fixar o commit aprovado pelo grupo e tratar avanços posteriores como fora do ambiente.
- **Decisão:** usar `https://github.com/odoo/odoo.git` no commit `a4b877245c9cb5e3d7152d1593a518170f115ca1`; nunca atualizar o pin automaticamente a partir do branch `19.0`.
- **Consequências:** todo build deve resolver esse commit em estado limpo; o digest OCI será registrado somente após construir a imagem correspondente; mudar a fonte exige nova versão e, depois do freeze, desvio e reexecução afetada.
- **Evidência:** decisão explícita do grupo, consultas `git ls-remote` em 30/08/2026 e `reproducibility/odoo-source.lock.json`.
- **Responsável:** grupo.
- **Afeta:** stack, Dockerfile, imagem Odoo, manifesto experimental, smoke tests, reprodução e runs.

## DEC-010 — Formato institucional do artigo final e separação do plano-mestre

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** o edital `EditalTCC_2026_2-V1` e o template `TemplateArtigo_TCC_FCI_2026` foram recuperados. O plano-mestre é um contrato operacional extenso e não atende, nem pretende atender, ao limite institucional do artigo final. O `.tex` do TCC I é histórico e não representa automaticamente o template atualizado de 2026.
- **Alternativas consideradas:** reutilizar o `.tex` antigo sem adaptação; converter o plano-mestre integral em artigo; manter o plano como fonte operacional e produzir um artigo separado a partir do template vigente.
- **Decisão:** manter o plano-mestre como artefato interno editável e produzir o artigo científico final em arquivo separado, sobre uma cópia saneada do template institucional de 2026, com 10 a 20 páginas, resumo e abstract de 150 a 250 palavras e os seis títulos literais exigidos pela FCI. Reancorar o cronograma para submissão inicial entre 03 e 09/11/2026.
- **Consequências:** detalhes de protocolo, schemas e evidências extensas irão para o repositório ou material suplementar; as seções científicas do plano serão mapeadas como subseções da estrutura oficial; o pacote local bruto permanece fora do Git e somente seus hashes e requisitos saneados serão versionados. Um único integrante será designado para cadastro e requerimento, os três autores serão conferidos, e reuniões semanais ou quinzenais de orientação terão presença e encaminhamentos registrados.
- **Evidência:** edital e template auditados em 30/08/2026, confirmação dos autores e do orientador pelo grupo, `docs/institutional-requirements.md` e `reproducibility/institutional-sources.lock.json`.
- **Responsável:** grupo; dúvidas de interpretação institucional serão confirmadas com o orientador e no Oriente.
- **Afeta:** Gate 0, cronograma, estrutura do artigo, checklist editorial, preparação da banca, privacidade e pacote de reprodução.

## DEC-011 — Ausência de participantes humanos

- **Data:** 30/08/2026
- **Status:** aceita
- **Contexto:** a arquitetura inclui um gate denominado *human-in-the-loop*, mas o experimento científico não pretende avaliar comportamento, desempenho ou decisão de pessoas. O template apenas exige indicar procedimentos éticos quando houver pesquisa com humanos ou animais.
- **Alternativas consideradas:** recrutar revisores humanos como participantes; conduzir estudo de usabilidade; simular deterministicamente o resultado de autorização e restringir a avaliação ao mecanismo técnico.
- **Decisão:** não haverá participantes humanos, recrutamento, entrevista, questionário, observação comportamental nem coleta de dados de participantes ou PII/dados operacionais reais no experimento. O approval gate será testado como controle técnico por tokens de fixture previamente definidos no ground truth. Dados cadastrais dos autores e do orientador ficam restritos ao fonte controlado do artigo. A nomenclatura metodológica permanece DSR com experimento controlado; o estudo será classificado como pesquisa aplicada, de abordagem predominantemente quantitativa, complementada por análise qualitativa de falhas.
- **Consequências:** métricas não poderão sustentar claims sobre qualidade, tempo, erro ou comportamento de revisores reais; a demanda de revisão é uma propriedade técnica potencial do pipeline, não carga observada de pessoas. O token terá contrato tipado e assinatura gerada em execução, e H4 usará um relógio end-to-end benigno comparável com injeção síncrona da fixture; tempos de disposição e validação do token serão apenas diagnósticos. Eventual inclusão futura de pessoas exige nova decisão, análise ética institucional e, depois do freeze, registro de desvio e novo protocolo.
- **Evidência:** confirmação explícita do grupo em 30/08/2026, dados integralmente sintéticos e escopo ético do plano.
- **Responsável:** grupo.
- **Afeta:** escopo, metodologia, threat model, métricas de revisão, ética, limitações e artigo.

## DEC-012 — Plano-mestre editável somente em Markdown

- **Data:** 31/08/2026
- **Status:** aceita
- **Contexto:** a geração do plano em DOCX/PDF por automação do Microsoft Word acrescenta tempo, dependência de ambiente gráfico e gates de metadados sem contribuir para o artefato científico. O artigo institucional continua sendo um arquivo separado no template FCI; ele não depende de converter o plano-mestre para Word.
- **Alternativas consideradas:** manter Markdown, DOCX e PDF obrigatórios em toda release; substituir imediatamente o conversor por outra cadeia de PDF; usar somente Markdown como fonte e preservar os binários da v1.2.1 como evidência histórica.
- **Decisão:** a partir da v1.2.2, o plano-mestre será publicado e editado somente em `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md`. Remover `build_tcc_docx.ps1` e não gerar novos DOCX/PDF do plano. O DOCX, o PDF, o validador e os manifests das versões anteriores permanecem no histórico sem representar a versão corrente. O artigo final continua separado e seguirá o template FCI vigente.
- **Consequências:** releases do plano ficam menores, independentes do Word e mais rápidas; o Markdown passa a ser o único artefato normativo corrente; links, estrutura, segurança e manifesto continuam obrigatórios. Uma futura necessidade de PDF exige decisão e pipeline próprios, sem restabelecer silenciosamente o DOCX.
- **Evidência:** decisão explícita do grupo em 31/08/2026 e distinção já fixada por DEC-010 entre plano operacional e artigo institucional.
- **Responsável:** grupo.
- **Afeta:** política de releases, `AGENTS.md`, `README.md`, `CHANGELOG.md`, árvore do repositório, artefatos históricos e scripts de geração/validação.

## DEC-013 — Garantia comprovável na fronteira JSON-2 de C1

- **Data:** 31/08/2026
- **Status:** aceita
- **Contexto:** a inspeção do controller JSON-2 do Odoo 19.0 mostrou que o transporte retira o campo especial `context` do payload e o aplica ao ambiente antes de chamar o método público. Por isso, o add-on não consegue distinguir entre contexto ausente e contexto já consumido pelo controller. A inspeção das ACLs também mostrou que um usuário interno mínimo pode conservar leituras de modelos básicos, embora não receba as permissões amplas de faturamento ou compras.
- **Alternativas consideradas:** afirmar rejeição literal do `context` dentro do executor; criar agora um controller customizado que preserve essa informação; usar JSON-2 nativa, não aceitar `context` no contrato de negócio, reconstruir um contexto interno controlado e testar invariância e ausência de mutações críticas por rotas alternativas.
- **Decisão:** manter JSON-2 como transporte. O gateway não enviará `context`; o contrato tipado do executor não aceitará esse campo; o executor usará valores confiáveis e um contexto interno mínimo para suas decisões. Testes com contexto hostil diretamente na JSON-2 deverão demonstrar que ele não altera autorização, empresa, estado ou efeito. A propriedade de menor privilégio será formulada como **nenhuma mutação crítica fora de `ap.security.executor.execute`**, e não como ausência absoluta de qualquer leitura ou chamada a modelos básicos.
- **Consequências:** a garantia passa a coincidir com o comportamento observável da plataforma e pode ser testada sem modificar o core. Leituras residuais inevitáveis serão inventariadas; `create`, `write`, `unlink`, `action_post`, pagamentos e demais mutações críticas deverão falhar fora do executor. Um controller customizado só será reconsiderado se o teste dinâmico mostrar que a neutralização é insuficiente.
- **Evidência:** `addons/rpc/controllers/json2.py` da revisão Odoo fixada; ACLs Community inspecionadas; futuros testes negativos de bypass, contexto e invariância.
- **Responsável:** grupo.
- **Afeta:** threat model, §§8.4 e 16.5–16.6, critérios de segurança, risco R23, checklist de freeze, desenho do add-on e testes de C1.
- **Complementa:** DEC-003 e D12; não altera hipóteses, métricas, margem, dataset ou comparação C0/C1.

## DEC-014 — Primeiro incremento executável e ambiente-base do laboratório

- **Data:** 31/08/2026
- **Status:** aceita
- **Contexto:** o repositório possuía o plano e os locks institucionais, mas ainda não continha ambiente executável. O host dispõe de Docker/Compose com daemon Linux `amd64`; seu Python é 3.13, enquanto o baseline do plano é Python 3.12. O snapshot local `odoo-19.0` não possui metadados Git e não pode provar procedência.
- **Alternativas consideradas:** instalar Python/PostgreSQL/Odoo diretamente no Windows; construir a partir do snapshot local ignorado; usar imagens móveis sem digest; adotar laboratório Docker-first com bases por digest e obter o Odoo diretamente da origem oficial no commit fixado.
- **Decisão:** o primeiro incremento M1/G1 será Docker-first e terá como único objetivo operacional subir PostgreSQL isolado e Odoo 19.0 Community construído da origem oficial em `a4b877245c9cb5e3d7152d1593a518170f115ca1`, inicializar somente módulos Community necessários, carregar fixtures integralmente sintéticas, autenticar via JSON-2, criar/ler exatamente uma conta de fornecedor em rascunho e demonstrar reset determinístico. A plataforma é `linux/amd64`; gateway e scripts Python usam Python 3.12 em contêiner. As bases Python 3.12 slim Bookworm e PostgreSQL 17 Bookworm ficam fixadas pelos manifests `linux/amd64` observados em 31/08/2026 e registradas em lock próprio. O build deve verificar `HEAD` contra o commit aprovado e incluir labels OCI de origem e revisão.
- **Consequências:** o host precisa somente de Git, PowerShell e Docker Compose; a pasta `odoo-19.0` continua exclusivamente exploratória e nunca entra no contexto de build. Banco não publica porta, Odoo publica apenas em loopback e credenciais/chaves existem somente em `.env` ou diretório local ignorado. O digest da imagem Odoo e a ligação fonte→imagem permanecem pendentes até um build bem-sucedido e não serão preenchidos por suposição.
- **Evidência:** auditoria local de versões; manifests de registry observados; Dockerfile, Compose, labels e futuros logs saneados de build/smoke/reset; `reproducibility/odoo-source.lock.json` e novo lock do ambiente.
- **Responsável:** grupo.
- **Afeta:** scaffold Docker, gateway JSON-2, fixtures, scripts de build/bootstrap/smoke/reset, testes e M1/G1.
- **Fora deste incremento:** LLM, PDF, OCR, C1, `ap_security_executor`, `action_post`, pagamentos, egress de rede, dataset piloto e qualquer dado real.

## DEC-015 — Adoção de PostgreSQL 18 para o banco do laboratório

- **Data:** 31/08/2026
- **Status:** aceita
- **Contexto:** o ambiente-base inicial utilizava PostgreSQL 17 Bookworm. O grupo solicitou a atualização do banco para PostgreSQL 18. A imagem oficial `postgres:18` (`18.6-trixie`) foi inspecionada no registry oficial para a plataforma `linux/amd64`.
- **Alternativas consideradas:** manter PostgreSQL 17; usar tag flutuante `postgres:18`; fixar a imagem `postgres:18` pelo digest imutável da plataforma `linux/amd64`.
- **Decisão:** atualizar o serviço de banco para `postgres:18@sha256:7341002d2b8c7c5bdd7542a671a95b36196c0b5b888daf454ae4fc33ba5346d7`. Atualizar `compose.yaml` e `reproducibility/lab-environment.lock.json` com o digest imutável e a versão observada (`18.6-trixie`).
- **Consequências:** o laboratório opera com a versão mais recente do PostgreSQL disponível na plataforma de destino; o isolamento em rede interna e a ausência de portas expostas fora do Compose permanecem inalterados.
- **Evidência:** pedido explícito do grupo em 31/08/2026; inspeção de manifest OCI via `docker buildx imagetools inspect`; testes de smoke test e persistência.
- **Responsável:** grupo.
- **Afeta:** `compose.yaml`, `reproducibility/lab-environment.lock.json`, smoke test e M1/G1.
- **Complementa:** DEC-014.
