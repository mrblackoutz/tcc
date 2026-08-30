# Registro de desvios do protocolo

**Estado atual:** protocolo ainda não congelado; nenhum desvio registrado.

Este arquivo passa a ser obrigatório no freeze. Ele preserva a especificação original e registra qualquer mudança posterior sem reescrever a história.

## Modelo obrigatório

```text
ID do desvio:
Data/hora:
Solicitante e aprovadores:
Versão congelada afetada:
Runs, pares e artefatos afetados:
Regra/configuração original:
Mudança realizada ou proposta:
Motivo e evidência:
Decisão tomada antes ou depois de observar resultados:
Impacto sobre validade interna, externa, de constructo e de conclusão:
Reexecução exigida:
Nova amostra independente exigida:
Tratamento no artigo: confirmatório | sensibilidade | exploratório | excluído
Commit, configuração e hashes:
```

## Regras

- não apagar nem editar retroativamente a regra original;
- numerar desvios sequencialmente como `DEV-001`, `DEV-002` e assim por diante;
- mudança de implementação que altere comportamento exige nova versão congelada e reexecução integral dos pares afetados;
- mudança de hipótese, endpoint, margem ou limite após observar o teste final não substitui a análise confirmatória original;
- nenhum desvio pode ser resolvido apenas por explicação verbal na banca.
