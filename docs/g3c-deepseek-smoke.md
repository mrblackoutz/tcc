# Gate G3c — smoke DeepSeek

**Decisões:** DEC-018 e DEC-020  
**Tarefa:** G3-05  
**Estado:** caminho implementado e aprovado offline; nenhuma chamada real executada neste commit

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

O marcador local `.runtime/evidence/g3c-deepseek-smoke.attempt.json` impede repetição silenciosa quando o resultado da primeira tentativa for incerto.

## 4. Comando autorizado

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_g3c.ps1 -ConfirmRealCall
```

O comando só deve ser executado depois de o commit de implementação estar limpo. Ele valida as topologias G3b/G3c, executa as suítes em contêiner sem rede, sobe apenas proxy e cliente, cria o marcador e então realiza uma única chamada.

## 5. Validação offline desta implementação

- `scripts/test_g3b_topology.py`: `PASS`, sem chamada real;
- `scripts/test_g3c_topology.py`: `PASS`, chave como bind exato read-only e somente proxy na rede externa;
- gateway/llm-client 0.5.0: `96 passed` com `--network none`, filesystem read-only e tmpfs;
- proxy 0.1.0: `6 passed` com `--network none`;
- smoke runtime G3b reexecutado: `PASS`, sem provedor, segredo ou download;
- contêineres temporários remanescentes: nenhum.

## 6. Definition of Done de G3-05

G3-05 só passa para `DONE` quando:

- [x] chave existe somente em arquivo local ignorado;
- [x] caminho real exige modo/profile explícito e proxy fixo;
- [x] chave é montada somente no cliente, como arquivo read-only;
- [x] runner não possui chave, egress ou acesso ao ERP;
- [x] G3b continua offline e aprovado;
- [ ] exatamente uma chamada real foi concluída, sem retry;
- [ ] manifesto local saneado passou no validador;
- [ ] proxy registrou exatamente um túnel permitido;
- [ ] logs/evidência foram verificados contra chave, `Authorization`, `Bearer`, documento, proposta e marcadores sensíveis;
- [ ] lock, documentação e backlog foram atualizados sem raw ou segredo.
