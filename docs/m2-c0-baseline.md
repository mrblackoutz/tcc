# Relatório técnico do vertical slice M2/C0

## 1. Estado e interpretação correta

O marco M2/G2 foi aceito tecnicamente em 31/08/2026, antes do congelamento experimental. Ele demonstra que o laboratório consegue executar, de ponta a ponta, o fluxo:

> PDF sintético benigno com camada de texto → extração sem OCR → proposta tipada → validação por schema → execução direta C0 → conta de fornecedor em rascunho no Odoo → remoção → restauração do estado.

Este resultado é uma **baseline de desenvolvimento do encanamento**, conforme DEC-017. Não é o C0 científico final, não usa LLM e não constitui evidência de competência de modelo, resistência a prompt injection ou eficácia de C1. O adaptador `deterministic-development/v1` está explicitamente proibido nas runs científicas.

## 2. Objetivo verificável

M2 elimina o risco de descobrir, durante o piloto, que PDF, contrato de proposta, integração JSON-2 ou oráculo de reset são incompatíveis. O marco é considerado concluído somente se:

1. um PDF real e local for lido por uma biblioteca de PDF, sem OCR;
2. o texto corresponder à fixture benigna pré-declarada;
3. a proposta for tipada, serializável e válida no JSON Schema versionado;
4. referências do documento forem resolvidas por chaves de negócio sintéticas, nunca por IDs fornecidos no documento;
5. a identidade técnica C0 criar exatamente uma conta de fornecedor em rascunho;
6. banco, pedido, linha de compra, produto, quantidade, preço e total coincidirem;
7. a conta for removida e o hash final coincidir com o inicial;
8. os testes negativos e o smoke integrado passarem.

## 3. Arquitetura implementada

```text
.runtime/documents/m2-benign-001.pdf
                 │
                 ▼
        extract_pdf_text (pypdf)
                 │  limites de bytes, páginas e caracteres
                 ▼
    DeterministicDevelopmentAdapter
                 │  parser estrito da fixture M2
                 ▼
      VendorBillProposal imutável
                 │
                 ▼
 JSON Schema draft 2020-12 + invariantes decimais
                 │
                 ▼
 resolve_c0_references por chaves de negócio
                 │
                 ▼
 Odoo JSON-2 / account.move.create (C0 direto)
                 │
                 ▼
 verificação → unlink → hash canônico restaurado
```

O transporte continua sendo JSON-2. Não há add-on C1, policy engine, aprovação simulada, detecção de ataque, postagem, pagamento ou alteração do core do Odoo. Limites de arquivo, schema e reconciliação de tipos são propriedades comuns de integridade do pipeline; eles não autorizam a ação e não impedem que um futuro C0 baseado em LLM proponha valores maliciosos estruturalmente válidos.

## 4. Contrato `vendor-bill-proposal/v1`

O schema está em `gateway/src/tcc_gateway/schemas/vendor_bill_proposal_v1.schema.json`. Ele usa JSON Schema draft 2020-12, recusa propriedades extras e exige:

| Grupo | Campos principais | Regra |
|---|---|---|
| Identidade do contrato | `schema_version`, `action`, `producer` | versão fixa; única ação aceita é criar rascunho |
| Classificação | `scenario_id`, `synthetic_data`, `fiscal_value` | dados sintéticos e sem valor fiscal |
| Proveniência | hashes SHA-256 do PDF e do texto, número de páginas | nenhum conteúdo bruto entra na evidência versionada |
| Chaves de negócio | fornecedor, PO, documento, moeda e conta bancária | strings limitadas; nenhum ID do ERP |
| Linhas | item, descrição, quantidade, preço e total | quantidade decimal textual; dinheiro com duas casas |
| Total | `total` | soma exata das linhas e reconciliação por `Decimal` |

O contrato aceita um identificador de produtor genérico para que o futuro adaptador LLM use a mesma fronteira. M2 exige especificamente `deterministic-development/v1` e registra que esse produtor não é permitido no experimento.

## 5. Documento de desenvolvimento

O PDF é gerado durante o smoke em `.runtime/documents`, portanto permanece ignorado pelo Git. Ele contém uma página, camada de texto ASCII e marcação explícita `DOCUMENTO SINTETICO - SEM VALOR FISCAL`. Seus campos derivam somente da fixture M1 já aceita: fornecedor, PO, moeda, conta bancária sintética, item, data e valor.

O documento M2 não é parte do dataset piloto/final, não recebe rótulo de ataque e não substitui a revisão por dois integrantes exigida para M3. PDFs criptografados, sem texto, estruturalmente inválidos ou acima dos limites são recusados. OCR continua fora do escopo.

## 6. C0 implementado neste marco

O executor C0:

- autentica com a identidade técnica dedicada criada no M1;
- resolve empresa, fornecedor, banco, PO, produto e linha de compra por chaves sintéticas;
- confere a competência mínima do cenário benigno, incluindo PO confirmado e valores reconciliados;
- chama diretamente `account.move.create`, sem policy engine C1;
- fixa `move_type='in_invoice'`, `state='draft'` por efeito do ERP e `auto_post='no'`;
- verifica o efeito por leitura independente;
- remove somente o rascunho criado pelo próprio smoke.

Essas verificações evitam uma baseline quebrada ou ambígua. Elas não são a defesa em profundidade de C1: um conteúdo indireto que leve o futuro LLM a produzir outra proposta estruturalmente válida continuará sendo objeto do experimento C0 × C1.

## 7. Testes negativos e integração

A suíte do gateway contém 41 testes. Além dos 19 testes herdados de M1, M2 cobre:

- PDF determinístico com camada de texto extraível;
- rejeição de PDF criptografado, sem texto, inválido, grande demais ou com páginas demais;
- campos ausentes, duplicados, desconhecidos ou com sintaxe inválida;
- total de linha e total geral inconsistentes;
- propriedade extra, data, moeda ou tipo incompatível com o schema;
- erro saneado que não repete o valor inválido;
- resolução por chaves de negócio, criação, verificação e restauração por cliente simulado;
- recusa de PO com valor divergente e de documento residual.

O smoke integrado reexecuta M1, sobe o Odoo fixado, gera o PDF, cria e verifica a conta, remove o rascunho e encerra os contêineres sem excluir volumes.

## 8. Evidência aceita

| Evidência | Valor |
|---|---|
| Cenário | `M2-BENIGN-001` |
| Adaptador | `deterministic-development/v1` |
| Testes | `41 passed` |
| PDF SHA-256 | `e36e2ca0107f728389ed947794d71e4402610a5ae096542f0035ef346f71d90a` |
| Texto SHA-256 | `402823e62cdb43dd6753153309d4c612f23825299281b7b06d5083789b9c8699` |
| Proposta SHA-256 | `a517e4e80e5ea712968d9a3f447165d3c964f4904a86db87b7b5157f0addb2e4` |
| Estado inicial | `224448b689468e1abc66b6556a0c7ebae686914ad1bef9ca11cdde53993aea0f` |
| Estado com rascunho | `ba07916cc8eb2d37a46033e37187b2385a41daff804911dbe287b0bdad714806` |
| Estado restaurado | `224448b689468e1abc66b6556a0c7ebae686914ad1bef9ca11cdde53993aea0f` |
| Imagem local gateway 0.2.0 | config digest `sha256:5c81dda4565efdc0d3352edd5223ca0addbab510e502fdc5e77de269320e16c0` |

Os valores correntes e o horário da execução estão em `reproducibility/lab-environment.lock.json`. A evidência detalhada `.runtime/evidence/m2-smoke.json` e o PDF permanecem locais e ignorados.

## 9. Reprodução

Na raiz do repositório:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test_m2.ps1
```

O script não oferece opção para apagar volumes. Ele revalida M1 com `-KeepRunning`, executa M2 e, por padrão, encerra os serviços preservando PostgreSQL e filestore. `-KeepRunning` deve ser usado somente para diagnóstico local.

## 10. Pendências que M2 não encerra

Para chegar a G3 e ao C0 científico ainda é obrigatório:

1. implementar o adaptador LLM real atrás do mesmo contrato;
2. selecionar e justificar modelo/configuração conforme W04, sem usar o conjunto final;
3. produzir e revisar por dois integrantes os 24 documentos do piloto;
4. demonstrar competência benigna do LLM no piloto;
5. congelar modelo, prompts, parâmetros, schema, dataset e ambiente antes das runs científicas.

O próximo incremento não deve promover o adaptador determinístico a baseline científica nem alterar hipótese, métrica, margem ou dataset com base neste smoke.

## 11. T-A2-PREFREEZE — aptidão de `partner_bank_id` para o oráculo da família A2

Executado em 05/09/2026 contra a imagem do commit fixado, com a identidade técnica C0 por JSON-2, exigido pelo achado ODO-02 sob DEC-022. As contas adversariais sintéticas foram semeadas com a identidade administrativa, porque o atacante modelado controla apenas o conteúdo do documento e nunca o cadastro mestre. Os quatro lançamentos criados foram removidos em rascunho e o estado foi conferido como limpo.

| Caso | Operação | Intenção | Observado | Persistiu |
|---|---|---|---|---|
| controle | `create` com beneficiário confiável | conta 1 | conta 1 | sim |
| a | `create` com conta de outro parceiro | conta 6 | conta 6 | sim |
| b | `create` com conta `allow_out_payment=False` | conta 3 | conta 3 | sim |
| c | `create` sem o campo e `write` adversarial | conta 6 | conta 6 | sim |
| d | `write` de `partner_id` após (a) | conta 6 | conta 1 | não |
| e | releitura independente após (d) | conta 6 | conta 1 | não |

Conclusão. O campo é apto ao oráculo de A2 sob uma condição: nenhuma escrita de `partner_id` pode ocorrer depois de `partner_bank_id` no mesmo fluxo. Fora dessa condição, o ERP recompõe o beneficiário confiável e o ataque desaparece do estado observável, o que geraria falso negativo concentrado em uma única família e inflaria a eficácia aparente de C1. O invariante de ordem está em §16.8 do plano e é verificado por assertion. O oráculo passa a registrar `present`, `acc_number_hash`, `belongs_to_vendor` e `allow_out_payment` em vez de um booleano de correspondência.

Reprodução: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_a2_partner_bank.ps1`. A evidência bruta fica em `.runtime/evidence/a2-partner-bank.json`, fora do Git.
