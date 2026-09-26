# Seleção dos modelos experimentais — W04/G3

**Decisão:** DEC-018

**Data da seleção:** 31/08/2026

**Estado:** modelos e papéis selecionados; G3-05 concluiu um smoke real sintético com alias legado e G3-06 concluiu outro com alias canônico em 26/09. Supervisão do runner, revisão independente, piloto, Qwen3 e freeze continuam pendentes.

## Decisão operacional

| Papel | Modelo selecionado | Uso | Obrigatoriedade |
|---|---|---|---|
| Bloco confirmatório principal | API DeepSeek, `model=deepseek-flash` no piloto aprovado em [DEC-029](decision-log.md#dec-029); seleção histórica de 31/08: `deepseek-v4-flash`/`DeepSeek-V4-Flash-0731` | piloto, competência de C0 e experimento principal C0 × C1 | obrigatório |
| Robustez e transportabilidade | Ollama, `qwen3:14b-q4_K_M` | repetição separada de 72 documentos em C0 × C1 | planejado após o núcleo; não sustenta as hipóteses confirmatórias |
| Contingência não ativa | `llama3.1:8b` | somente se Qwen3 for inviável e houver nova decisão anterior ao freeze | não selecionado para as runs atuais |

O código ativo solicita `deepseek-flash`, validado em **uma inferência real sintética**, sem Odoo ou comparação C0/C1. `DeepSeek-V4-Flash-0731` identifica apenas o backend associado ao alias legado na data da seleção. Desde 10/09/2026, o nome legado é roteado temporariamente para V4.1 Flash, conforme [DEC-024](decision-log.md#dec-024). O smoke histórico de 24/09 solicitou `deepseek-v4-flash` e recebeu `deepseek-flash`; o smoke G3-06 solicitou e recebeu `deepseek-flash`. Nenhum desses nomes identifica um snapshot imutável.

No Ollama, a tag escolhida é a quantização explícita `qwen3:14b-q4_K_M`. A tag curta `qwen3:14b` não será usada nas runs, pois pode mudar de alvo. Mesmo a tag explícita só ficará congelada depois de registrar localmente seu manifest completo e os digests dos blobs.

## Desenho preservado

Cada modelo forma um bloco próprio. Dentro do bloco, C0 e C1 recebem o mesmo documento e usam o mesmo modelo, artefato ou alias observado, prompt-base, schema, limites, parâmetros e política de retry.

```text
dataset e ground truth
├── DeepSeek (alias móvel; backend observado por data)
│   ├── C0
│   └── C1
└── Qwen3 14B Q4_K_M
    ├── C0
    └── C1
```

É proibido usar DeepSeek em C0 e Qwen3 em C1, ou o inverso. Esse desenho mudaria simultaneamente modelo e arquitetura e impediria atribuir a diferença observada a C0/C1.

O orçamento vigente continua sendo:

- piloto DeepSeek: 24 documentos × 2 condições × 3 repetições = 144 runs;
- bloco principal DeepSeek: 180 documentos × 2 condições × 3 repetições = 1.080 runs;
- bloco Qwen3: 72 documentos × 2 condições × 3 repetições = 432 runs, somente depois do núcleo;
- ablações e conjunto defense-aware permanecem como definidos no plano-mestre.

O exemplo de 120 documentos apresentado durante a discussão não substitui a meta pré-piloto de 180 documentos. Qualquer alteração de tamanho amostral será decidida antes do freeze a partir do piloto, da precisão, do poder e do orçamento, nunca a partir dos resultados finais.

## Configuração comum

As seguintes decisões já estão fixadas:

- *thinking* explicitamente desligado no núcleo dos dois modelos;
- `temperature=0` quando aceito; caso o endpoint rejeite zero, usar o menor valor aceito e fixá-lo antes do freeze;
- contrato semântico único `vendor-bill-proposal/v1`;
- modelo propõe, mas não autoriza nem executa ação;
- referências de negócio sintéticas no output; nenhum ID interno do Odoo é aceito do documento;
- resposta inválida, tool call ausente, múltiplo ou incompatível e violação de schema são outcomes do sistema, não erros a ocultar por parsing permissivo;
- no máximo duas novas tentativas somente para falhas transitórias previamente classificadas, com política idêntica em C0 e C1.

O adapter deverá solicitar uma única proposta estruturada pelo mecanismo nativo compatível de cada provedor e normalizá-la para o mesmo schema. JSON output e tool calling melhoram a estrutura do transporte, mas não constituem defesa: a validação comum recusa campos desconhecidos e o policy engine de C1 continua sendo a fronteira de decisão.

Ainda serão fixados no piloto, antes do freeze:

- system prompt e hashes de cada mensagem fixa;
- limite de entrada e saída, timeout e backoff;
- versão exata do contrato de tool/JSON enviada a cada API;
- `top_p`, seed quando suportada e demais defaults efetivamente aplicados;
- regra para resposta truncada, vazia, múltiplas tool calls e recusa;
- limiares de latência, custo e demanda potencial de revisão;
- lote temporal e janela de execução usados para reduzir drift do serviço externo.

<a id="g3-06"></a>

### G3-06 — configuração técnica ratificada para o pré-piloto, não freeze final

A [configuração técnica pré-piloto (DEC-029)](decision-log.md#dec-029) foi ratificada por Gustavo com conexão de 10 s. Um [smoke canônico (DEC-030)](decision-log.md#dec-030) separado passou em 26/09/2026: uma chamada sintética, `deepseek-flash` solicitado e retornado, 685 tokens de entrada, 127 de saída, aproximadamente 1,28 s no adapter, zero retries, um túnel e manifesto saneado. O SHA-256 do manifesto local é `45f7722115020ec445ef89cf0cde2d7e96448315bdb9d595ddabc01caa6af5be`; o lock guarda proveniência e limitações. Uma resposta não estima cauda de latência, taxa de erro, custo em escala ou competência C0.

| Parâmetro | Valor aprovado para o pré-piloto | Situação |
|---|---|---|
| Alias solicitado | `deepseek-flash` | configurado no adapter e Compose; smoke sintético real passou; revisão independente pendente |
| `thinking` | `disabled` | fixado para o núcleo; padrão do provedor é ligado |
| `temperature` | `0` | candidato já aceito no smoke; manter igual em C0/C1 |
| `top_p`, penalidades e seed | omitidos | `top_p` é ignorado no modo sem thinking; os demais não são pressupostos como controles de reprodutibilidade |
| Formato e transporte | `json_object`, `stream=false`, uma escolha | manter schema estrito local; JSON válido não basta para autorização |
| `max_tokens` | 2.048 | valor atual do adapter, sujeito a truncamentos observados no piloto |
| Timeout de conexão | 10 s | implementado como default DeepSeek; não altera o default Ollama |
| Timeout de inatividade de leitura | 120 s | implementado como default DeepSeek; não equivale a prazo total por causa de keep-alives |
| Prazo de parede por tentativa | 180 s | [estágio técnico pré-freeze (DEC-031)](decision-log.md#dec-031) limita e verifica a espera do runner; ainda não supervisiona o encerramento do processo remoto |
| Orçamento da chamada lógica | 300 s | implementado no estágio técnico com relógio monotônico e testes offline; não integrado ao runner Odoo |
| Retries | até 2 novas tentativas para timeout/conexão ou HTTP 408/429/5xx | política comum C0/C1 implementada e testada offline; o adapter faz uma tentativa; 409 é permanente e desfecho incerto não é repetido |
| Espera entre tentativas | 2 s, depois 4 s, sem jitter | implementada no estágio técnico, igual em C0/C1; não repetir erros de modelo/schema/truncamento |

Antes do piloto, ainda são necessários a revisão independente, a integração do estágio técnico ao runner com captura de estado Odoo e supervisão de processo remoto, o contrato de `missing` de SCI-03 e a validação de competência de C0. O grupo deverá conferir truncamentos, custo e classificação idêntica dos erros em C0/C1 sem usar o conjunto final. O timeout de leitura de 120 s sozinho não impõe prazo total: keep-alives podem mantê-lo aberto. O smoke aprovado não autoriza chamadas pagas adicionais por si só.

Um estudo de *thinking* ligado versus desligado não integra o núcleo. Se for executado, será exploratório, posterior e formalizado em decisão própria, sem substituir resultados confirmatórios.

## Proveniência exigida

Cada run deverá preservar fora do Git o request e o response brutos e produzir um registro saneado com, no mínimo:

- provedor, base URL e endpoint;
- alias solicitado e valor de modelo/versionamento devolvido pelo serviço, quando existir;
- mapeamento de versão documentado pelo provedor e data de consulta;
- timestamp UTC e identificador de request saneado;
- modo de raciocínio e parâmetros enviados;
- defaults relevantes observados;
- hashes do system prompt, mensagens fixas, schema, documento, dataset, configuração e commit Git;
- tokens de entrada, saída, cache e raciocínio quando informados;
- latência, status, categoria de erro e retries;
- tabela de preço e data usadas no cálculo de custo.

Para DeepSeek, o pacote científico deverá distinguir reexecução posterior com o mesmo alias de reprodução analítica dos dados já coletados. Não será alegado que o provedor preservou o mesmo backend sem evidência retornada ou publicada.

Para Qwen3, o lock final deverá incluir versão do Ollama, nome exato, manifest completo, digests de todos os blobs, quantização, tamanho, context length usado, parâmetros e hash de qualquer `Modelfile`. A tag de catálogo, sozinha, não satisfaz o freeze.

## Segurança e isolamento

A chave DeepSeek nunca entra em Git, Compose, argumento de linha de comando, log, fixture ou evidência saneada. O adapter deverá lê-la de arquivo de segredo ou variável de ambiente local e remover cabeçalhos e payloads sensíveis de erros.

A topologia G3b mantém `lab`, `llm_control` e `llm_egress` internas. Somente o proxy participa de uma rede externa; gateway, Odoo e PostgreSQL não participam dela, e o cliente não participa de `lab` nem recebe credenciais do ERP. Os testes negativos offline estão registrados em `docs/g3b-egress-topology.md`. O smoke G3c de 24/09 passou após a DEC-024 registrar que o alias solicitado `deepseek-v4-flash` passou a ser servido como V4.1 Flash; o retorno observado foi `deepseek-flash`. A competência do C0 e a igualdade C0/C1 continuam para o piloto.

Requests e responses brutos, ainda que sintéticos, permanecem em armazenamento externo criptografado e com acesso controlado. O Git recebe somente hashes, metadados saneados e exports sintéticos aprovados por dois integrantes.

## Viabilidade local observada

Em 31/08/2026 foram observados:

- Ollama 0.30.10;
- NVIDIA GeForce RTX 3060 Ti com 8 GiB de VRAM;
- 66,5 GiB livres na unidade do projeto;
- apenas `llama3.1:8b` instalado; Qwen3 ainda ausente;
- artefato de catálogo `qwen3:14b-q4_K_M` com aproximadamente 9,3 GB.

O Qwen3 não cabe integralmente na VRAM observada e deverá usar offload parcial. Isso não o invalida, mas impede prometer desempenho antes do smoke. Após o download autorizado pelo operador, o gate de viabilidade deve registrar carregamento, CPU/GPU efetivamente usadas, memória, tempo até o primeiro token, tokens por segundo, latência total, context length, estabilidade e ausência de OOM. Se o modelo for inviável, o bloco confirmatório DeepSeek continua inalterado e qualquer contingência exige nova decisão.

## Definition of Ready para implementar G3

- [x] modelo primário e modelo secundário selecionados em DEC-018;
- [x] papéis e orçamento amostral separados;
- [x] modo sem *thinking* definido para o núcleo;
- [x] contrato comum já existe em M2;
- [x] decisão de egress mínimo registrada em DEC-020, com chamadas reais bloqueadas até a implantação e os testes negativos;
- [x] arquivo de exemplo lista somente nomes e valores não sensíveis/fictícios, sem chave;
- [x] adapters DeepSeek e Ollama implementados sob interface comum no commit `b2deec8`;
- [x] mocks cobrem JSON válido/inválido, schema, truncamento, escolha/tool call único ou múltiplo, timeout, rate limit, erro de provedor, drift e sanitização; 82 testes passaram sem rede;
- [x] `llm-client`, API interna, redes separadas, proxy allowlisted e testes negativos offline aprovados em G3b; 91 testes do gateway/cliente e 6 do proxy passaram sem chamada externa;
- [ ] Qwen3 baixado com autorização, manifest completo fixado e smoke de hardware aprovado;
- [x] DeepSeek validado com chamada sintética mínima, manifesto saneado e varredura de segredo/log em 24/09/2026;
- [ ] parâmetros e prompts do piloto versionados e hasheados.

## Fontes oficiais consultadas

- DeepSeek, modelos, recursos e preço: <https://api-docs.deepseek.com/quick_start/pricing/>;
- DeepSeek, histórico de versões: <https://api-docs.deepseek.com/updates/>;
- DeepSeek, controle do modo de raciocínio: <https://api-docs.deepseek.com/guides/thinking_mode/>;
- Ollama, catálogo e tags Qwen3: <https://ollama.com/library/qwen3/tags>;
- Qwen, model card Qwen3-14B: <https://huggingface.co/Qwen/Qwen3-14B>.

As páginas são referências de seleção, não substitutos do manifest efetivamente usado. Preço, alias, tamanho de contexto e tag de catálogo deverão ser reobservados e datados no piloto e no freeze.
