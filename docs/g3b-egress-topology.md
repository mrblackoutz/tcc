# Relatório técnico G3b — isolamento executável de egress

## 1. Estado e interpretação correta

O gate offline G3b foi atendido tecnicamente em 01/09/2026 pelo commit `f2d7f5fcc728cd601702c1ec1ebf5fcb25d4761e`, sob DEC-020. O incremento materializa o processo `llm-client`, a API interna tipada, três redes internas, um proxy CONNECT com allowlist exata e um smoke reproduzível de isolamento e transporte simulado.

G3b não realizou chamada DeepSeek ou Ollama, não estabeleceu túnel ao destino externo permitido, não leu chave e não baixou modelo. Portanto, ele comprova a fronteira, os contratos e as negações offline, mas não demonstra conectividade com o provedor, competência do modelo, custo, latência, alias retornado ou C0 científico. Esses pontos permanecem para G3c e o piloto.

## 2. Topologia materializada

| Componente | Redes | Credenciais presentes | Saída permitida no gate corrente |
|---|---|---|---|
| PostgreSQL e Odoo | `lab` interna | somente credenciais próprias do laboratório | nenhuma |
| gateway | `lab` e `llm_control`, ambas internas | Odoo; nenhuma chave LLM | somente serviços internos necessários |
| `llm-client` | `llm_control` e `llm_egress`, ambas internas | nenhuma Odoo/PostgreSQL/DeepSeek no modo G3b | API interna e proxy; nenhuma rota direta |
| `egress-proxy` | `llm_egress` interna e `proxy_external` | nenhuma | política fixa para `CONNECT api.deepseek.com:443` |

Somente o proxy participa de `proxy_external`. O cliente não participa de `lab`; o proxy não participa de `lab` nem de `llm_control`. Os dois novos serviços permanecem atrás do profile Compose `g3b`, não publicam porta no host, usam filesystem somente leitura, `tmpfs`, `no-new-privileges` e removem todas as capabilities Linux.

## 3. API interna do llm-client

O serviço `tcc-gateway 0.4.0` expõe internamente:

- `GET /healthz`, que declara `mode=mock` e `real_transport=false`;
- `POST /v1/proposals`, regido por `llm-client-request/v1`;
- provider explícito `deepseek` ou `ollama` sob o mesmo contrato;
- documento extraído com hashes, páginas e tamanho limitados;
- até oito mensagens `system`/`user`, com limites individuais e agregados;
- resposta `llm-client-response/v1` com proposta completa e metadados saneados.

O schema é fechado, o hash do texto é recalculado e divergências falham sem eco do payload. O processo recusa qualquer configuração diferente de `mock` e aborta se receber variável de credencial do Odoo, PostgreSQL ou DeepSeek. A implementação real permanece deliberadamente inacessível até G3c.

## 4. Proxy de passagem

O proxy não termina TLS e aceita somente HTTP/1.1 `CONNECT` para o hostname e porta fixos da DEC-020. Sua política:

- nega hostname alternativo, porta alternativa e IP literal;
- exige `Host` coerente e recusa headers de autorização enviados ao proxy;
- limita o cabeçalho inicial a 8 KiB e recusa estrutura ambígua;
- resolve o hostname no próprio proxy e recusa endereços privados, loopback, link-local, reservados ou não globais;
- registra somente categoria `allow`, `deny_*` ou falha de transporte, sem headers e corpo;
- preserva os bytes TLS já recebidos depois do `CONNECT` sem inspecionar conteúdo.

O teste unitário reconhece o destino nominal com resolução simulada e nega as alternativas. O smoke runtime não abre o túnel nominal, porque isso já seria observação de egress externo; esse primeiro contato permanece agrupado ao smoke G3c autorizado.

## 5. Evidência executada

O comando versionado foi:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_g3b.ps1
```

Ele executou, nesta ordem:

1. validação estática do Compose resolvido sem imprimir o ambiente;
2. build das imagens locais;
3. 91 testes do gateway/`llm-client` em contêiner sem rede e somente leitura;
4. 6 testes do proxy em contêiner sem rede e somente leitura;
5. inicialização isolada sob o projeto temporário `tcc-g3b-offline`;
6. probe runtime de credenciais, DNS do ERP, rota direta, negações do proxy e API mock;
7. varredura de logs por classes proibidas;
8. remoção dos contêineres e redes temporários, sem remover volumes do laboratório principal.

Saídas finais saneadas:

```text
91 passed in 1.11s
Ran 6 tests in 0.006s — OK
g3b-topology-check/v1 — pass — real_provider_call=false
g3b-offline-probe/v1 — pass — real_provider_call=false
G3b offline safety smoke: PASS
```

| Evidência | Valor |
|---|---|
| Commit de implementação | `f2d7f5fcc728cd601702c1ec1ebf5fcb25d4761e` |
| Gateway/cliente | `tcc-gateway:0.4.0` |
| ID local da imagem gateway/cliente | `sha256:d08fd12918ccb70765e8f4244ee559eac74e007c0fa914b8369e081b0ea58b92` |
| Proxy | `tcc-egress-proxy:0.1.0` |
| ID local da imagem proxy | `sha256:b426a2843665be934f40db00ad92beac97ffa29dd616001fb72c1529053c0b60` |
| Plataforma observada | `linux/amd64` |
| Testes | 91 gateway/cliente + 6 proxy |
| Chamada DeepSeek/Ollama | 0 |
| Túnel ao destino permitido | 0 |
| Download de modelo | 0 |
| Chave criada ou lida | não |
| Log com classe proibida | não encontrado |
| Recursos temporários restantes | nenhum contêiner/rede do projeto de smoke |

Os IDs são IDs/configuração de imagem Docker local, não `RepoDigest` nem manifest OCI publicado. Eles identificam a evidência pré-freeze nesta máquina e não substituem os digests dos artefatos finais.

## 6. Testes negativos e limites

| Requisito DEC-020 | Evidência G3b | Estado |
|---|---|---|
| gateway/Odoo/banco sem rede externa | associação exclusiva a redes marcadas `internal`, validada sobre o Compose resolvido | atendido por política executável |
| cliente sem rede `lab` e sem credencial ERP | topologia, ambiente e DNS runtime | atendido |
| cliente sem Internet direta | somente redes internas + conexão direta negativa no probe | atendido |
| somente proxy em rede externa | membership exato validado no Compose resolvido | atendido |
| host/IP/porta alternativos negados | testes unitários e runtime | atendido |
| destino nominal reconhecido | parser e resolução pública testados com transporte simulado | atendido offline |
| túnel real ao destino nominal | deliberadamente não executado | pendente G3c |
| logs sem segredo/payload | logger fechado e varredura do smoke | atendido |

O teste de rota direta usa em conjunto a propriedade `internal` do Docker e uma tentativa negativa. Uma conexão que apenas expirasse não bastaria isoladamente; por isso o aceite também valida a associação exata de redes. A disponibilidade real de DNS, TCP, TLS e API do provedor permanece não observada.

## 7. Definition of Done de G3b

- [x] `llm-client` separado, sem credencial Odoo/PostgreSQL/DeepSeek no perfil corrente;
- [x] API interna tipada e schema fechado;
- [x] modo real impossível até mudança explícita de código/configuração em G3c;
- [x] redes `lab`, `llm_control` e `llm_egress` internas;
- [x] somente o proxy participa da rede externa;
- [x] allowlist exata, recusa de IP literal e proteção contra resolução não pública;
- [x] testes negativos e probe mock passam;
- [x] logs saneados e recursos temporários removidos;
- [x] nenhuma chamada, chave ou download;
- [ ] smoke DeepSeek G3c autorizado e saneado;
- [ ] artefato/smoke Qwen3 G3d;
- [ ] parâmetros, competência, custo e latência G3e.

## 8. Próxima etapa

G3c exige autorização operacional separada. Antes da execução, o código deverá habilitar o transporte real somente por opção explícita, montar a chave local ignorada em modo somente leitura, manter a URL fixa e produzir manifest saneado. O smoke deve usar um único documento sintético, confirmar que o túnel nominal funciona, registrar alias/modelo retornado, uso, latência e hashes e repetir a varredura de logs. Nenhum dado real ou pagamento integra essa etapa.
