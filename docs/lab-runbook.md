# Runbook do laboratório M1–M2

## 1. Finalidade e limite

Este runbook descreve o ambiente executável dos marcos M1 e M2, autorizados por DEC-014 a DEC-017. Com dados exclusivamente sintéticos e sem valor fiscal, M1 demonstra que:

1. o Odoo 19.0 Community é construído da origem oficial no commit fixado;
2. o artefato executado está vinculado a um manifest OCI verificável;
3. uma identidade técnica C0 não administrativa autentica pela API JSON-2;
4. uma conta de fornecedor em rascunho pode ser criada com referência bancária e linha vinculada a pedido de compra confirmado;
5. a remoção do rascunho restaura exatamente o hash canônico do estado inicial.

M2 acrescenta um vertical slice benigno: gera localmente um PDF com camada de texto, extrai-o sem OCR, produz uma proposta tipada e validada, resolve chaves de negócio e executa o mesmo efeito C0 antes de restaurar o estado. M2 não executa LLM, prompt injection, C1, postagem de conta, pagamento, mensageria externa ou dados reais. O protocolo científico continua pré-congelamento.

## 2. Pré-requisitos

- Windows PowerShell 5.1 ou PowerShell 7;
- Git;
- Docker Desktop com daemon Linux e plataforma linux/amd64;
- Docker Compose v2 e Buildx;
- acesso à internet no primeiro build para obter fontes e dependências;
- porta de loopback configurada em ODOO_HTTP_PORT, por padrão 8069.

O script de build cria, quando necessário, o builder local tcc-oci-builder com driver docker-container. Nada é enviado a registry.

## 3. Arquivos e responsabilidades

| Caminho | Responsabilidade |
|---|---|
| compose.yaml | PostgreSQL 18, Odoo, gateway, rede interna, volumes e restrições de contêiner |
| odoo/Dockerfile | build do Odoo a partir do commit aprovado |
| gateway/Dockerfile | runtime Python 3.12 não privilegiado do gateway e dos testes |
| gateway/constraints.txt | versões resolvidas das dependências Python do build M2 |
| odoo/fixtures/bootstrap_m1.py | empresa, fornecedor, conta bancária, produto, PO e identidade C0 sintéticos |
| scripts/build_odoo_image.ps1 | exportação OCI/Docker, validação de digests, labels, plataforma e commit |
| scripts/smoke_test.ps1 | orquestração do build, testes, bootstrap, smoke e desligamento |
| scripts/smoke_test_gateway.py | criação, leitura, assertions, remoção e hashes do estado |
| scripts/smoke_test_m2.ps1 | revalidação de M1, orquestração do vertical slice M2 e atualização do lock |
| scripts/smoke_test_m2.py | PDF, proposta, execução direta C0, assertions e evidência saneada M2 |
| gateway/src/tcc_gateway/schemas/vendor_bill_proposal_v1.schema.json | contrato estrito e versionado da proposta |
| docs/m2-c0-baseline.md | interpretação, cobertura, evidência e limites científicos de M2 |
| reproducibility/odoo-source.lock.json | procedência da fonte e ligação fonte-imagem |
| reproducibility/lab-environment.lock.json | componentes, controles e últimos aceites M1/M2 saneados |

.env e todo o conteúdo de .runtime/ são locais, ignorados pelo Git e não devem ser compartilhados. A pasta contém credenciais, uma fixture com identificadores internos, evidência detalhada, o PDF sintético M2 e exports locais de imagem.

## 4. Primeira execução

Na raiz do repositório:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1

O segundo comando inclui a revalidação completa de M1. Para executar somente M1, usar `scripts/smoke_test.ps1`.

O script new_local_env.ps1:

- gera senhas aleatórias para PostgreSQL e para a administração local do Odoo;
- grava .env e .runtime/odoo.conf sem exibir valores;
- cria os diretórios locais de segredos, evidências e documentos;
- não cria chave de API antecipadamente.

O script smoke_test.ps1:

1. exporta uma única resolução do build para um layout OCI e um tar Docker;
2. calcula o SHA-256 dos bytes do manifest e do config;
3. exige que manifest e config sejam objetos distintos;
4. verifica descriptor, plataforma linux/amd64, índice OCI e referência config-manifest;
5. carrega o tar Docker e exige que o ID da imagem seja o config digest do layout OCI;
6. confere labels de origem, revisão e imagem-base e lê /opt/odoo/.tcc-source-commit;
7. constrói o gateway e executa 41 testes no Python 3.12 fixado;
8. inicializa base, web, rpc, account e purchase;
9. carrega fixtures sintéticas e gera uma chave RPC com validade de 12 horas para tcc_c0_api;
10. cria e lê uma única account.move de fornecedor em rascunho;
11. verifica banco, PO, linha de compra, valor, estado e auto_post;
12. remove o rascunho, compara os hashes e encerra os contêineres sem excluir volumes.

Um resultado aceito termina com:

    41 passed
    M1_FIXTURE_BOOTSTRAP=PASS
    M1_JSON2_VENDOR_BILL=PASS
    M1 smoke PASSED

O script retorna código diferente de zero diante de qualquer divergência.

O script `smoke_test_m2.ps1` reexecuta esse aceite M1 sem apagar volumes e, mantendo os serviços apenas durante a execução:

1. gera `.runtime/documents/m2-benign-001.pdf` de forma determinística;
2. extrai a camada de texto com `pypdf`, sob limites de bytes, páginas e caracteres;
3. produz e valida `vendor-bill-proposal/v1` com o adaptador de desenvolvimento;
4. resolve empresa, fornecedor, banco, PO, produto e linha por chaves sintéticas;
5. cria e verifica exatamente um rascunho pela identidade C0;
6. remove o rascunho e exige igualdade dos hashes inicial e restaurado;
7. grava somente hashes e invariantes saneados em `.runtime/evidence/m2-smoke.json` e no lock.

Um resultado M2 aceito termina com `41 passed`, `M1 smoke PASSED`, `M2_PDF_TO_C0_DRAFT=PASS` e `M2 smoke PASSED`.

## 5. Evidência aceita em 31/08/2026

| Evidência | Valor |
|---|---|
| Fonte Odoo | https://github.com/odoo/odoo.git |
| Commit Odoo | a4b877245c9cb5e3d7152d1593a518170f115ca1 |
| Plataforma | linux/amd64 |
| Manifest OCI local | sha256:3e0bcf8e796820e89577b1db24b4dbb54a63669f66384c4b61577068adf1f392 |
| Config da imagem carregada | sha256:c85221764b096dde2df68c50e2da634147b10c14dcfb98bf57f71f62a14bd1f2 |
| Cenário | M1-SYNTHETIC-001 |
| Hash inicial | 59f35a642fb61228f64fa2c0c016dafccec157a5eb7b338dd3ed360722398653 |
| Hash com rascunho | 4af857529f31c027965d4beb8937e0861b19ae7737595a93c1067954965b1986 |
| Hash restaurado | 59f35a642fb61228f64fa2c0c016dafccec157a5eb7b338dd3ed360722398653 |

Os locks versionados são a fonte corrente desses valores. O arquivo detalhado .runtime/evidence/m1-smoke.json é local; ele não contém chave ou IDs, mas permanece fora do Git pela política geral de evidência bruta.

### 5.1 Evidência M2

| Evidência | Valor |
|---|---|
| Cenário | M2-BENIGN-001 |
| Adaptador | deterministic-development/v1 — proibido para runs científicas |
| PDF | e36e2ca0107f728389ed947794d71e4402610a5ae096542f0035ef346f71d90a |
| Proposta | a517e4e80e5ea712968d9a3f447165d3c964f4904a86db87b7b5157f0addb2e4 |
| Hash inicial | 224448b689468e1abc66b6556a0c7ebae686914ad1bef9ca11cdde53993aea0f |
| Hash com rascunho | ba07916cc8eb2d37a46033e37187b2385a41daff804911dbe287b0bdad714806 |
| Hash restaurado | 224448b689468e1abc66b6556a0c7ebae686914ad1bef9ca11cdde53993aea0f |

O relatório técnico e a interpretação científica correta estão em `docs/m2-c0-baseline.md`. O PDF e a evidência detalhada continuam fora do Git.

## 6. Operação recorrente

### Executar o aceite completo

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1

### Executar M1 e M2

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1

M2 sempre revalida M1 e não possui opção `-RecreateVolumes`. Se o bootstrap encontrar um rascunho M2 residual de uma execução interrompida, ele o remove de modo controlado, registra a ocorrência na fixture e o smoke reprova em vez de ocultar o estado anterior.

O bootstrap é idempotente para as fixtures M1. Se encontrar uma conta com a referência sintética em estado diferente de rascunho, ele interrompe e não a remove.

### Manter os serviços para diagnóstico

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 -KeepRunning
    docker compose ps
    docker compose down

docker compose down encerra contêineres e rede, mas preserva os volumes.

### Construir e verificar apenas a imagem Odoo

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_odoo_image.ps1

O build atualiza os campos de imagem nos dois locks e marca o smoke como pendente até que smoke_test.ps1 termine com sucesso.

### Recriar volumes

A opção -RecreateVolumes apaga dados locais do PostgreSQL e do filestore Odoo. O script primeiro restringe o alvo aos volumes rotulados pelo projeto e ao namespace tcc-odoo-lab_*, mas a operação continua destrutiva. Só executar com autorização explícita do responsável:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 -RecreateVolumes

Não combinar rotação de .env com volumes antigos: a nova senha de banco deixa de corresponder à credencial persistida. Planejar new_local_env.ps1 -Force e a recriação dos volumes como uma única manutenção autorizada.

## 7. Segurança operacional

- nunca copiar valores de .env, .runtime/odoo.conf ou .runtime/secrets para terminal, commit, issue ou mensagem;
- nunca usar documento fiscal, conta bancária, pessoa ou empresa real;
- nunca promover o PDF M2 ao dataset piloto/final ou usar o adaptador determinístico em runs científicas;
- a porta do PostgreSQL não é publicada;
- o Odoo é publicado somente em 127.0.0.1;
- a rede Compose é interna, sem egress durante o runtime;
- o gateway e o Odoo usam filesystem somente leitura, no-new-privileges e todas as capabilities removidas;
- a identidade C0 possui somente os grupos internos necessários ao baseline e não possui base.group_system;
- a chave C0 é revogada e regenerada pelo bootstrap, expira em 12 horas e só existe em arquivo local ignorado;
- o manifest OCI e o tar Docker permanecem em .runtime/build; não há push implícito;
- depois do freeze, não reconstruir imagem nem alterar scripts sem registrar desvio e reexecutar os pares afetados.

## 8. Diagnóstico

| Sintoma | Verificação | Ação |
|---|---|---|
| acesso negado ao daemon ou a .docker/config.json | docker version e docker compose version em PowerShell local | habilitar acesso ao Docker Desktop; não copiar configuração ou credenciais para o repositório |
| porta 8069 ocupada | conferir ODOO_HTTP_PORT sem exibir outras variáveis | escolher outra porta apenas para uso local e registrar a configuração se houver run |
| aviso without_demo=all | configuração local criada por versão anterior do bootstrap | não afeta a execução observada; corrigir somente em rotação planejada, pois a versão atual gera True |
| aviso de add-ons locais inválidos | .runtime/odoo.conf antigo aponta para pasta ainda vazia | a versão atual só adicionará o caminho quando existir add-on versionado |
| config digest igual ao suposto manifest | lock ou script anterior à DEC-016 | recusar a evidência e executar o build corrigido; os dois digests devem ser distintos |
| hash final diferente do inicial | consultar apenas a evidência saneada e o estado sintético | interromper; não apagar volume como forma de esconder a divergência |
| conta sintética não está em rascunho | bootstrap recusa a remoção | preservar o estado para diagnóstico e registrar a causa antes de qualquer correção |

## 9. Encerramento e entrega

Antes de commit:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
    git status --short
    git diff --check
    git diff --cached --name-only
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1 -StagedOnly

Preparar arquivos por caminhos explícitos. .env, .runtime, odoo-19.0, logs, volumes, banco, filestore e documentos locais nunca entram no commit.
