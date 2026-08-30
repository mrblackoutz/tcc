# Registro de decisões

Este log complementa as decisões D01–D12 do plano-mestre. Nenhuma decisão material deve permanecer apenas em conversa, memória individual ou código.

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
- **Evidência:** D11, W01–W02 e inspeção do snapshot local; commit/checksum upstream ainda deve ser congelado.
- **Responsável:** grupo.
- **Afeta:** stack, containers, integração, referências e reprodução.

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
- **Status:** parcialmente aceita; parâmetros finais dependem do piloto
- **Contexto:** trocar modelo entre C0 e C1 confundiria efeito do modelo com efeito da arquitetura.
- **Alternativas consideradas:** modelos diferentes por condição; múltiplos modelos no núcleo; um modelo primário fixo e segundo opcional.
- **Decisão:** usar exatamente o mesmo modelo/configuração em C0 e C1; manter 180 documentos como meta pré-piloto; tratar 10 pontos percentuais de BTSR como margem candidata.
- **Consequências:** seleção do modelo e justificativa da margem devem ocorrer antes do freeze e sem consultar o teste final.
- **Evidência:** W04–W06, H3 e §§14–15 do plano 1.2.
- **Responsável:** grupo e orientador para aprovação da margem.
- **Afeta:** piloto, manifesto, poder, custo e análise estatística.

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
