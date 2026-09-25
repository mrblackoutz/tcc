# Gate G3c — smoke DeepSeek

**Decisões:** DEC-018, DEC-020 e DEC-024
**Tarefa:** G3-05  
**Estado:** concluído tecnicamente em 24/09/2026; resposta tipada e manifesto saneado aprovados

## 1. Objetivo e limite

G3c comprova somente que um documento sintético mínimo atravessa a fronteira de egress aprovada, recebe uma resposta tipada do DeepSeek e gera metadados saneados. O gate não mede resistência a prompt injection, não demonstra competência geral do C0, não integra Odoo e não constitui run científica.

O script recusa execução sem `-ConfirmRealCall`, exige árvore Git limpa, chave local ignorada e ausência de marcador/evidência anterior. Depois de iniciar a tentativa, qualquer falha é classificada como chamada potencialmente realizada; não há retry automático.

## 2. Fronteiras executáveis

| Componente | Redes | Segredos | Função |
|---|---|---|---|
| `g3c-runner` | somente `llm_control`, interna | nenhum | envia exatamente um request sintético e grava apenas manifesto saneado |
| `llm-client-g3c` | `llm_control` e `llm_egress`, internas | arquivo DeepSeek exato e read-only | valida contrato, chama o adapter e devolve proposta/metadados tipados |
| `egress-proxy` | `llm_egress` interna e `proxy_external` | nenhum | permite apenas `CONNECT api.deepseek.com:443`, sem terminar TLS |
| gateway/Odoo/PostgreSQL | sem participação no profile G3c executado | nenhum segredo DeepSeek | permanecem fora do smoke e sem egress externo |

O runner não recebe proxy nem chave. O cliente não participa da rede `lab`, não recebe URL/token Odoo ou credencial PostgreSQL e não possui rota externa direta. Somente o proxy participa da rede externa.

## 3. Request e evidência

O cenário fixo `G3C-DEEPSEEK-BENIGN-001` contém uma nota sintética marcada como sem valor fiscal. O adapter solicita:

- `POST https://api.deepseek.com/chat/completions`;
- `model=deepseek-v4-flash`;
- `thinking={"type":"disabled"}`;
- `temperature=0`;
- `response_format={"type":"json_object"}`;
- `stream=false` e uma única escolha.

O arquivo local `.runtime/evidence/g3c-deepseek-smoke.json` preserva somente status, commit, alias/modelo, ID saneado, fingerprint quando disponível, tokens, latências e hashes de request, response, conteúdo, mensagens, schema, documento e proposta. Documento, prompt, proposta, resposta bruta, cabeçalho e chave não são persistidos nesse manifesto nem enviados ao Git.

O marcador local `.runtime/evidence/g3c-deepseek-smoke.attempt.json` impede repetição silenciosa quando uma tentativa não produz o manifesto de sucesso. Marcadores anteriores são preservados localmente em `.runtime/evidence/archive/`, fora do Git, e somente seus metadados saneados e hashes entram na documentação.

## 4. Primeira tentativa inconclusiva

Em 02/09/2026, o operador autorizou a primeira tentativa sobre o commit `0fc66ce8981259e7dd0f675d9e21263f247c8bcb`. O proxy e o cliente ficaram saudáveis; o contêiner do runner foi criado e iniciado, mas saiu com código 1 após aproximadamente dois segundos. Nenhum manifesto de sucesso foi escrito.

A causa observada no orquestrador foi a promoção, pelo Windows PowerShell 5.1 sob `ErrorActionPreference=Stop`, de uma linha normal de progresso do Docker Compose em `stderr` a erro terminante. O `finally` removeu os serviços antes que os logs saneados fossem preservados. Portanto, não se afirma que a chamada ocorreu nem que não ocorreu: o limite auditável é de zero a uma chamada. Nenhum retry foi executado.

O marcador privado foi atualizado como `failed-or-call-outcome-uncertain-no-automatic-retry` e permanece ignorado pelo Git. Seu SHA-256 saneado é `7d11fb1648ec782b26ecaa352a58f16b4c765182ffefedb6d43f0e45c8c4a6d3`. O script passou a capturar progresso nativo com `ErrorActionPreference=Continue`, decidir pelo exit code do processo e preservar categoria saneada/quantidade de túneis antes de falhar. Uma nova tentativa exige autorização operacional explícita; não é continuação automática da anterior.

## 5. Tentativas posteriores e bloqueio externo

Após nova autorização do operador, uma segunda tentativa foi executada sobre o commit `ffa155d636da64f8f84c2ffcfb1f38af56adfbfd`. A captura corrigida comprovou um túnel permitido e classificou a falha no cliente interno como HTTP 502, ainda sem preservar a categoria segura retornada pelo adapter. Não houve manifesto de sucesso nem retry. O marcador arquivado possui SHA-256 `921d81fd47c7bdb8c700ecb502175cb551906784948706b3304a1290eaddd2a3` e 500 bytes.

Para remover essa ambiguidade sem persistir corpo de erro, o runner passou a extrair somente a categoria normalizada e o status HTTP já saneados pelo `llm-client`. A mudança foi aprovada em 97 testes offline e versionada no commit `ef956d2014e08967882aa8d79b7f9307504617e0`.

Uma terceira tentativa única, também autorizada, alcançou `api.deepseek.com:443` por exatamente um túnel permitido. O provedor recusou a requisição com HTTP 402, classificado como `llm_client_request_rejected_provider_http_402`. Isso comprova a fronteira de egress e uma resposta do endpoint, mas não comprova autenticação utilizável, inferência, modelo retornado, JSON estruturado ou competência. Nenhum manifesto de sucesso foi escrito e nenhum retry ocorreu. O marcador arquivado possui SHA-256 `df6ca79a99d816ee585d82d9d157f7d8487b365dd59c2299fc45234bce2c1b7a` e 526 bytes.

## 6. Retomada em 24/09 e aceite

Após a adição de saldo, a tentativa 4 abriu um túnel permitido, mas o runner registrou apenas HTTP 502; o marcador arquivado tem SHA-256 `a0c93e97e373cd0efb7cb7659b26783b212bdedd1b7970859589739f787469f5`. A telemetria foi corrigida para preservar a categoria segura sem depender de status HTTP upstream. A tentativa 5, também única e sem retry, identificou `llm_client_model_mismatch`, com um túnel permitido; o marcador arquivado tem SHA-256 `997c228ddd5bf1a9bab2dd79209b161bbe200c2a3c747fc88a7bab01367a3818`.

A documentação oficial DeepSeek de 10/09 informa que o alias legado `deepseek-v4-flash` foi roteado para V4.1 Flash. A decisão foi registrada no commit local `4efde97` antes da correção e integrada ao histórico remoto como DEC-024; a allowlist do adapter e do runner passou a aceitar apenas os novos identificadores documentados, mantendo o alias solicitado e registrando o retorno real. A suíte offline passou em 102 testes do gateway/cliente e 6 do proxy na árvore da tentativa aceita. Após a integração com a base remota v1.2.12, a árvore corrente passou em 105 + 6 testes offline, sem nova chamada ao provedor.

A tentativa 6, sobre o commit `606771377e4ac5f8dfb6142f608f86f3aab0998a`, **passou**. Houve uma chamada real sintética, zero retries, `deepseek-v4-flash` solicitado e `deepseek-flash` retornado. O manifesto local `.runtime/evidence/g3c-deepseek-smoke.json` possui 1.957 bytes e SHA-256 `5c6f48af59643475d824bb41acb6008658baff2e54e1beb254779a0f3d5e22bc`. O marcador local da tentativa aprovada possui 442 bytes e SHA-256 `200619594c838927e22635dd0407c3667943e475a675d6787569563c0c1f73dd`. Os logs e a evidência passaram na varredura de segredo e classes proibidas; o proxy registrou exatamente um túnel permitido. O manifesto contém 11 hashes, 685 tokens de entrada, 127 de saída e latência do adapter de aproximadamente 1,22 s. O smoke não é uma run científica nem substitui o piloto/C0 competente.

## 7. Comando autorizado

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_g3c.ps1 -ConfirmRealCall
```

O comando só deve ser executado depois de o commit de implementação estar limpo. Ele valida as topologias G3b/G3c, executa as suítes em contêiner sem rede, sobe apenas proxy e cliente, cria o marcador e então realiza uma única chamada.

## 8. Validação offline desta implementação

- `scripts/test_g3b_topology.py`: `PASS`, sem chamada real;
- `scripts/test_g3c_topology.py`: `PASS`, chave como bind exato read-only e somente proxy na rede externa;
- gateway/llm-client 0.5.0: `102 passed` com `--network none`, filesystem read-only e tmpfs após a atualização controlada do modelo retornado;
- proxy 0.1.0: `6 passed` com `--network none`;
- smoke runtime G3b reexecutado: `PASS`, sem provedor, segredo ou download;
- captura corrigida do `stderr` validada com runner inofensivo que apenas imprimiu texto, sem subir cliente/proxy ou ler chave: `PASS`;
- contêineres temporários remanescentes: nenhum.

## 9. Definition of Done de G3-05

G3-05 só passa para `DONE` quando:

- [x] chave existe somente em arquivo local ignorado;
- [x] caminho real exige modo/profile explícito e proxy fixo;
- [x] chave é montada somente no cliente, como arquivo read-only;
- [x] runner não possui chave, egress ou acesso ao ERP;
- [x] G3b continua offline e aprovado;
- [x] tentativa inconclusiva registrada sem alegar sucesso ou ausência de chamada;
- [x] falha de captura do orquestrador corrigida sem nova chamada;
- [x] endpoint permitido alcançado e HTTP 402 registrado sem corpo, chave ou payload;
- [x] proxy registrou exatamente um túnel permitido na tentativa diagnóstica;
- [x] exatamente uma chamada real foi concluída na tentativa aceita, sem retry;
- [x] manifesto local saneado passou no validador;
- [x] logs/evidência foram verificados contra chave, `Authorization`, `Bearer`, documento, proposta e marcadores sensíveis;
- [x] lock, documentação e backlog foram atualizados sem raw ou segredo.
