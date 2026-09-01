# Fronteira de egress e contrato dos adapters LLM — G3

**Decisão:** DEC-020

**Estado:** desenho aceito; G3a e G3b offline comprovados; smoke DeepSeek G3c, artefato/smoke Qwen3 e piloto ainda pendentes

**Data:** 31/08/2026

## 1. Objetivo e limite desta etapa

Este documento transforma a seleção de modelos da DEC-018 em um desenho implementável sem abrir a rede do laboratório nem antecipar o piloto. G3a implementou adapters, schema, mocks e saneamento; G3b materializou `llm-client`, redes e proxy e aprovou os testes offline em 01/09/2026. Esses gates não autorizam baixar Qwen3, fazer chamada DeepSeek, inserir chave ou tratar transporte simulado como C0 científico competente.

## 2. Trust boundaries

```text
                         rede externa
                              │
                    api.deepseek.com:443
                              │ TLS sem terminação
                    ┌─────────▼─────────┐
                    │ allowlist proxy   │  somente CONNECT para host/porta fixos
                    └─────────▲─────────┘
                              │ rede interna de egress
                    ┌─────────┴─────────┐
                    │ llm-client        │  chave DeepSeek; sem chave Odoo
                    │ adapters comuns   │  ou acesso ao Ollama local
                    └─────────▲─────────┘
                              │ rede interna de controle
                    ┌─────────┴─────────┐
                    │ gateway/runner    │  sem egress externo
                    └─────────▲─────────┘
                              │ rede interna lab
          ┌───────────────────┼───────────────────┐
          │                   │                   │
        Odoo              PostgreSQL          outbox local
      sem egress           sem egress          sem egress
```

O proxy não participa de `lab`. O `llm-client` não participa de `lab` e não recebe URL, token ou identidade do Odoo. O gateway não participa da rede externa. Para o bloco Qwen3, o Ollama pertence a uma rede interna local do cliente e não pode selecionar modelos cloud durante runs.

## 3. Política de destinos

| Origem | Destino permitido | Destinos negados |
|---|---|---|
| gateway, runner, Odoo, PostgreSQL, executor e outbox | serviços internos estritamente necessários | qualquer endereço externo |
| `llm-client` DeepSeek | proxy interno configurado | Internet direta, Odoo, PostgreSQL e outbox |
| proxy de egress | `api.deepseek.com:443` por `CONNECT` | IP literal, outro hostname, porta ou protocolo |
| `llm-client` Qwen3 | Ollama local fixado | Ollama cloud, Internet, Odoo e PostgreSQL |

A validação do `base_url` no adapter deve recusar credenciais embutidas, query, fragmento, host, esquema ou porta divergentes. Esse teste evita erro de configuração e SSRF acidental; o bloqueio efetivo continuará sendo responsabilidade da rede.

## 4. Contrato comum

Os dois adapters recebem:

- mensagens preparadas pela camada de prompt, sem inferir se a run é C0 ou C1;
- `scenario_id` obtido do manifest confiável do dataset;
- hashes e número de páginas do `ExtractedPdf`;
- modelo, temperatura, limite de saída e timeouts explicitamente configurados.

Os dois devolvem:

- uma `VendorBillProposal` validada como `vendor-bill-proposal/v1`;
- metadados saneados de provedor, endpoint, modelo solicitado/devolvido, modo de raciocínio, motivo de término, uso, durações e hashes;
- uma categoria estável de erro quando não houver proposta válida.

O adapter não autoriza, consulta o Odoo, escolhe ferramenta nem executa retry. A mesma instância/configuração poderá alimentar C0 e C1; o delta científico começa antes, na construção de proveniência, e depois, na política/autorização/executor.

## 5. Schema visto pelo modelo

O schema auxiliar `vendor-bill-model-output/v1` contém somente:

- `vendor_ref`, `purchase_order_ref`, `document_ref`;
- `invoice_date`, `currency`, `bank_account_ref`;
- `lines` com item, descrição, quantidade, preço e total;
- `total`.

O adapter injeta de fonte confiável `producer`, `scenario_id`, `source`, `synthetic_data=true`, `fiscal_value=false`, `schema_version` e `action`. A proposta completa passa novamente pelo schema `vendor-bill-proposal/v1` e pelos invariantes decimais. Isso não impede que um ataque mude fornecedor, beneficiário ou valor; apenas impede que conteúdo externo falsifique a proveniência do experimento.

## 6. Protocolo de transporte

### DeepSeek

- base fixa `https://api.deepseek.com`;
- `POST /chat/completions`;
- `model=deepseek-v4-flash`;
- `thinking={"type":"disabled"}`;
- `response_format={"type":"json_object"}`;
- `stream=false` e exatamente uma escolha;
- chave em arquivo de segredo ou variável local, nunca em argumento, Compose, fixture, log ou Git.

### Ollama

- API local `/api/chat` em endpoint explicitamente permitido;
- `model=qwen3:14b-q4_K_M`;
- `think=false`;
- `format` recebe o schema auxiliar completo;
- `stream=false` e ausência de tool calls inesperadas;
- nenhuma chave para a API local e nenhum uso de modelo cloud.

`temperature=0` é o valor candidato definido na DEC-018. Limites, timeout, seed e demais parâmetros continuam pré-freeze e serão fixados pelo piloto, igualmente para C0/C1 dentro de cada bloco.

## 7. Saneamento e custódia

Erros podem expor apenas provedor, categoria estável, status HTTP numérico permitido e indicação de retry. Não podem copiar headers, corpo, URL com query, caminho de segredo, documento, prompt, resposta ou exceção original. IDs e nomes devolvidos passam por allowlist de caracteres e tamanho antes de entrar em metadados.

O Git recebe hashes e metadados saneados. Requests/responses brutos pertencem ao armazenamento externo criptografado, com acesso controlado e cópia imutável. O logger do proxy deve registrar somente decisão de rede e destino aprovado, sem TLS interception e sem conteúdo.

## 8. Matriz mínima de testes

| Camada | Casos obrigatórios |
|---|---|
| Configuração | fonte de segredo ausente/ambígua; `repr` saneado; modelo e endpoint divergentes; URL com credencial/query/fragmento |
| Request DeepSeek | endpoint, headers e payload esperados; JSON mode; *thinking* desligado; não streaming |
| Request Ollama | endpoint e payload esperados; schema em `format`; `think=false`; não streaming |
| Response | válido; vazio; JSON inválido; schema inválido; truncado; escolha/tool call múltiplo ou inesperado; modelo divergente; raciocínio inesperado |
| Falha | timeout, transporte, 429 e 5xx com categoria/retry corretos e sem eco de conteúdo |
| Rede antes do smoke | nega egress de gateway/Odoo/banco; nega acesso do cliente ao ERP; nega Internet direta do cliente; permite somente host/porta no proxy; nega IP literal e destinos alternativos |

## 9. Gates

- **G3a — código isolado:** adapters, schema e mocks passam; nenhuma rede real é usada.
- **G3b — egress executável:** **atendido offline em 01/09/2026**; topologia, API mock, política e testes negativos passaram sem contato externo, conforme `docs/g3b-egress-topology.md`.
- **G3c — smoke DeepSeek:** autorizado pelo operador, documento sintético mínimo, segredo fora dos logs, alias/modelo retornado registrado.
- **G3d — smoke Qwen3:** download autorizado, manifest/blobs fixados e hardware aprovado sem OOM.
- **G3e — piloto:** prompts, parâmetros, retry, competência, custo e latência aprovados antes do freeze.

Até G3b, qualquer método de transporte real deve permanecer inacessível pelo ambiente do laboratório. Até G3c/G3d, os respectivos provedores permanecem com estado `not-smoked` nos manifests.

## 10. Fontes oficiais observadas

- DeepSeek Chat Completions: <https://api-docs.deepseek.com/api/create-chat-completion/>;
- DeepSeek JSON Output: <https://api-docs.deepseek.com/guides/json_mode/>;
- DeepSeek Thinking Mode: <https://api-docs.deepseek.com/guides/thinking_mode/>;
- Ollama Chat API: <https://docs.ollama.com/api/chat>;
- Ollama Structured Outputs: <https://docs.ollama.com/capabilities/structured-outputs>;
- Ollama Thinking: <https://docs.ollama.com/capabilities/thinking>.
