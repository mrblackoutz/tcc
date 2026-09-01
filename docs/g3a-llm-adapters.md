# Relatório técnico G3a — adapters LLM simulados e saneados

## 1. Estado e interpretação correta

O gate G3a foi atendido tecnicamente em 31/08/2026 pelo commit `b2deec89fedb34e42e93c079999100b98c5bf1a0`, sob DEC-018 e DEC-020. O incremento implementa os contratos de transporte DeepSeek/Ollama, o schema auxiliar de output, a normalização para `vendor-bill-proposal/v1`, a configuração de segredos e uma suíte inteiramente simulada.

G3a não realizou chamada à API DeepSeek, não acessou Ollama, não baixou Qwen3 e não abriu a rede `lab`. Portanto, ele não demonstra competência benigna do modelo, resistência a prompt injection, viabilidade da GPU, custo, latência de provedor ou conclusão do C0 científico. O estado correto é **adapter implementado e testado com mocks; provedor ainda não submetido a smoke**.

## 2. Escopo implementado

Foram adicionados:

- `DeepSeekProposalAdapter` para `POST https://api.deepseek.com/chat/completions`;
- `OllamaProposalAdapter` para `POST /api/chat` em três endpoints locais explicitamente permitidos;
- interface comum `LLMProposalAdapter` e request/result compartilhados;
- `vendor-bill-model-output/v1`, schema fechado somente para campos de negócio propostos pelo LLM;
- injeção confiável de produtor, cenário, hashes, páginas e marcadores sintéticos;
- metadados saneados com hashes, modelo, término, uso e duração;
- categorias estáveis para falhas de configuração, transporte, provedor e conteúdo;
- leitura da chave DeepSeek por arquivo local ou variável de ambiente, exatamente uma fonte por vez;
- configuração de exemplo sem chave, chamada real ou destino alternativo.

O pacote foi versionado como `tcc-odoo-gateway 0.3.0`. O serviço `gateway` do Compose continua exclusivamente na rede interna `lab`, sem variável DeepSeek, sem chave de provedor e sem rota externa. Nesta etapa, os adapters são uma biblioteca destinada ao futuro processo separado `llm-client`; sua presença no pacote não autoriza o gateway atual a realizar egress.

## 3. Contrato e proveniência

O modelo pode propor apenas:

- referências sintéticas de fornecedor, pedido, documento e conta bancária;
- data e moeda;
- linhas, quantidades, preços e totais.

O modelo não recebe autoridade para definir `producer`, `scenario_id`, `source`, `synthetic_data`, `fiscal_value`, `schema_version` ou `action`. Esses campos são derivados do runner/documento confiável depois da validação do output. Em seguida, o objeto completo passa pelo schema `vendor-bill-proposal/v1` e por reconciliação decimal.

Essa separação protege a integridade da evidência, mas não mascara o fenômeno estudado: uma prompt injection ainda pode induzir o LLM a propor fornecedor, beneficiário, referência ou valor malicioso que satisfaça o schema. Em C0, esses argumentos tipados seguem para a integração funcional; em C1, o policy engine os confrontará com estado confiável.

## 4. Transporte DeepSeek

O request simulado comprova:

- endpoint fixo `https://api.deepseek.com/chat/completions`;
- `model=deepseek-v4-flash`;
- `thinking={"type":"disabled"}`;
- `response_format={"type":"json_object"}`;
- `temperature=0`, `stream=false` e limite de saída explícito;
- prompt com instrução JSON e schema auxiliar;
- autenticação somente no header em memória, excluída de `repr`, hashes e erros.

O parser aceita exatamente uma escolha finalizada com `stop`. Resposta vazia, truncada, múltipla, com tool call, raciocínio inesperado, modelo divergente, JSON inválido ou schema inválido falha sem parsing permissivo. O backend documentado `DeepSeek-V4-Flash-0731` e o alias solicitado são os únicos valores pré-piloto aceitos como retorno de modelo.

## 5. Transporte Ollama

O request simulado comprova:

- endpoint local `/api/chat`;
- `model=qwen3:14b-q4_K_M`;
- `think=false`, `stream=false` e `temperature=0`;
- schema completo no campo `format`;
- ausência de header de autorização;
- rejeição de Ollama Cloud, porta alternativa, path adicional e modelo divergente.

O teste não comprova que o artefato existe localmente. O Qwen3 continua ausente e não congelado; manifest, blobs, offload e desempenho permanecem para G3d.

## 6. Saneamento e política de falhas

Exceções expõem somente provedor, categoria estável, status HTTP numérico quando aplicável e flag de retry. Corpo de erro, exceção original, chave, prompt, documento e resposta não são copiados. Os metadados de sucesso contêm hashes do request, corpo, conteúdo, mensagens, system prompt e schema, nunca os valores brutos.

O adapter executa exatamente uma tentativa. `timeout`, falha de transporte, HTTP 408/409, 429 e 5xx são classificados como potencialmente transitórios, mas o retry não ocorre no adapter. O runner futuro aplicará a política única para C0/C1 e registrará cada tentativa.

## 7. Testes e evidência

A imagem `tcc-gateway:0.3.0`, construída do commit acima, executou:

```text
docker run --rm --network none --read-only --tmpfs /tmp:size=64m,mode=1777 \
  tcc-gateway:0.3.0 python -m pytest -q -p no:cacheprovider

82 passed in 0.50s
```

O comando não montou segredo, documento externo, socket, volume do Odoo ou rede. A suíte anterior tinha 41 testes; G3a acrescentou 41 casos e preservou todos os testes M1/M2.

| Evidência | Valor |
|---|---|
| Commit de implementação | `b2deec89fedb34e42e93c079999100b98c5bf1a0` |
| Imagem local | `tcc-gateway:0.3.0` |
| ID local da imagem Docker | `sha256:ead78dcf1f486e604dc8c034ab9e3677b8139619d4ed2a5aee97fda4d0555a59` |
| Plataforma | `linux/amd64` |
| Testes | `82 passed` |
| Rede do teste | `none` |
| Filesystem do teste | somente leitura; `/tmp` efêmero |
| Chamadas DeepSeek | 0 |
| Chamadas Ollama | 0 |
| Downloads de modelo | 0 |
| Chave criada ou lida | não |

O ID acima é o ID/configuração da imagem local, não um `RepoDigest` nem um manifest OCI publicado. Ele identifica a evidência pré-freeze desta máquina e não substitui o digest do artefato final exigido antes das runs.

## 8. Matriz de cobertura

| Família | Cobertura aprovada |
|---|---|
| Configuração | segredo ausente/ambíguo; arquivo ilegível sem eco do path; endpoint e modelo fora da decisão; temperatura não registrada |
| DeepSeek request | URL, header, alias, JSON mode, schema, *thinking* off, temperatura e streaming |
| Ollama request | URL local, ausência de auth, tag exata, schema, `think=false`, temperatura e streaming |
| Contrato | output válido; proveniência confiável; propriedade extra; valor inválido; schema completo final |
| Estrutura | vazio, JSON inválido, truncado, ausência/multiplicidade de escolha, tool call único/múltiplo, raciocínio inesperado e modelo divergente |
| Falhas | timeout, 429, 400 e 503; retryability e status saneados |
| Regressão | todos os testes de configuração Odoo, JSON-2, PDF, proposta, executor C0 e estado M1/M2 |

## 9. Definition of Done de G3a

- [x] DEC-020 registrada antes do código;
- [x] interface comum entre os dois adapters;
- [x] schema auxiliar fechado e proposta final validada;
- [x] proveniência fora do controle do modelo;
- [x] chave ausente de `repr`, erro, fixture e Git;
- [x] endpoint/modelo allowlisted em código;
- [x] mocks sem rede cobrem sucesso e falhas requeridas;
- [x] imagem 0.3.0 construída e testada em rede `none`;
- [x] segurança do repositório aprovada;
- [ ] serviço `llm-client` separado e proxy allowlisted implantados;
- [ ] testes negativos de rede de G3b;
- [ ] smoke DeepSeek de G3c;
- [ ] download/lock/smoke Qwen3 de G3d;
- [ ] prompts, parâmetros e competência fixados no piloto G3e.

## 10. Próxima etapa autorizável

G3b deve materializar a topologia da DEC-020 sem chamar provedores: redes internas separadas, processo cliente sem credencial Odoo, proxy de passagem com allowlist exata e testes negativos. Somente depois desse gate o grupo deve fornecer a chave localmente e autorizar um único smoke sintético DeepSeek. O download do Qwen3 continua sendo decisão operacional separada.
