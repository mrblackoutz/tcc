# AGENTS.md — regras operacionais do TCC

## Escopo

Estas regras valem para todo o repositório. O projeto deve ser tratado como potencialmente público, mesmo quando o remoto estiver privado.

## Fontes de verdade

1. `Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md` é a fonte normativa do escopo científico, das decisões D01–D15, do protocolo e dos critérios de conclusão.
2. `docs/decision-log.md` registra decisões surgidas durante a construção.
3. `docs/deviation-log.md` preserva qualquer divergência depois do congelamento experimental.
4. `CHANGELOG.md` registra versões publicadas do plano-mestre.
5. `reproducibility/odoo-source.lock.json` fixa a origem e o commit do Odoo; o digest OCI permanece pendente até a construção da imagem.
6. `docs/institutional-requirements.md` traduz o edital e o template vigentes em gates do TCC II.
7. `reproducibility/institutional-sources.lock.json` registra hashes e anomalias das fontes institucionais mantidas fora do Git.
8. O conteúdo efetivamente desenvolvido no relatório do TCC I orienta a continuidade; seu título anterior não define o escopo atual.

Se implementação e documentação divergirem, não escolher silenciosamente um dos lados: interromper a mudança, registrar a divergência e decidir qual deve ser corrigido.

## Fluxo obrigatório para qualquer mudança

Antes de editar:

1. ler as seções afetadas do plano, este arquivo e as decisões relacionadas;
2. executar `git status --short` e preservar alterações do usuário;
3. identificar o ID da decisão que autoriza a mudança ou criar uma entrada proposta no decision log;
4. verificar se o protocolo já foi congelado e, se foi, aplicar também as regras de desvio e reexecução.

Durante a mudança:

- manter o escopo delimitado a Contas a Pagar, Odoo 19.0 Community, C0/C1 e prompt injection indireta;
- avaliar somente manipulação de campos, redirecionamento de beneficiário e ação crítica sem autorização; a exposição de dados, mensagens ao fornecedor, canários e tokenização foram retirados pela [decisão de redução do escopo (DEC-023)](docs/decision-log.md#dec-023);
- registrar decisões antes de implementá-las, incluindo alternativas descartadas e consequências;
- não modificar o core do Odoo; extensões pertencem a add-ons versionados;
- preservar igualdade entre C0 e C1 nas variáveis controladas;
- não ajustar hipótese, métrica, margem, dataset ou defesa com base no conjunto final;
- usar dados sintéticos marcados como sem valor fiscal.

## Princípio de factibilidade (DEC-082)

O objetivo é entregar um experimento **factível e honesto**, não um perfeito. Sem prazo cumprido não há resultado, e perseguir detalhes mínimos já consumiu semanas. Regras para qualquer agente ou integrante:

- parar uma revisão, teste ou correção quando o risco restante não altera uma métrica do experimento, uma conclusão do artigo ou a segurança dos dados; registrar em uma linha e seguir;
- não abrir nova rodada de hardening, nova documentação de evidência ou novo commit-âncora para um achado de severidade baixa; anotar no relatório e tratar só se sobrar prazo;
- um teste ou revisão que já falha fechado (rejeita a entrada incoerente) não precisa de uma segunda barreira equivalente;
- ao escolher entre "completo" e "suficiente para o piloto e o artigo", escolher o suficiente e declarar a limitação, em vez de escondê-la ou eliminá-la;
- o que **não** é negociável continua igual: não vazar segredos ou dados reais, não ajustar hipótese, métrica, dataset ou defesa depois de ver o conjunto final, e não apresentar como aceito o que não foi revisado.

Depois da mudança:

1. executar testes proporcionais ao risco;
2. atualizar decisão, documentação, checklist e changelog aplicáveis;
3. validar o Markdown corrente; não regenerar DOCX/PDF do plano-mestre, conforme DEC-012;
4. executar a verificação de segurança do repositório antes e depois de preparar o commit;
5. relatar separadamente o que foi implementado, testado, pendente ou apenas proposto.

## Versionamento do plano-mestre

- Toda versão publicada do plano deve corresponder a um commit Git dedicado.
- Atualizar número, data, status, histórico interno e `CHANGELOG.md` no mesmo commit.
- Incluir no commit o Markdown, changelog, decisões, manifesto da release e scripts que afetem sua validação. DOCX/PDF do plano não são artefatos correntes.
- Usar mensagem no padrão `docs(plan): release vX.Y[.Z] — resumo`.
- Não misturar uma versão do plano com código experimental não relacionado.
- Não reescrever commit de versão já publicado com amend, squash, rebase ou force-push. Correções posteriores geram nova versão e novo commit.
- Se uma versão for publicada por processo externo em commits fora do padrão, preservar o histórico, registrar a exceção no decision log e criar um manifesto/commit-âncora auditável; não corrigir o remoto sem autorização explícita.
- Usar `git add` com caminhos explícitos. É proibido preparar versão com `git add -A`, `git add .` ou globs amplos.
- Não enviar qualquer commit ao remoto sem pedido explícito do usuário; dados sensíveis nunca podem ser enviados.

## Registro de decisões e desvios

Cada decisão material deve conter: ID, data, status, contexto, alternativas, decisão, consequências, evidência, responsável e seções/artefatos afetados.

Na documentação corrente, apresentar referências pelo significado, com ID e link: por exemplo, [contribuição das camadas (RQ4)](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#rq4) e [revisão independente do plano (DEC-022)](docs/decision-log.md#dec-022). Explicar siglas na primeira ocorrência de cada seção ou apontar para o [glossário](Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#glossario). Não renumerar IDs para fechar lacunas nem reescrever registros históricos; IDs retirados permanecem reservados. A leitura rápida e as definições ficam no plano, sem criar um manual paralelo.

Depois do freeze:

- preservar a configuração original;
- registrar toda mudança em `docs/deviation-log.md`;
- mudanças de implementação que afetem runs exigem nova versão congelada e reexecução integral dos pares afetados;
- mudanças de hipótese, endpoint, margem ou limite após observar resultados tornam-se exploratórias, salvo validação em amostra independente.

## Segredos, privacidade e dados

Nunca versionar, anexar a issues, copiar para logs ou expor em saída de ferramenta:

- chaves de API, tokens, senhas, cookies, credenciais de banco ou strings de conexão;
- chaves privadas, certificados privados, arquivos `.env` ou credenciais de nuvem;
- documentos fiscais reais, dados bancários reais, PII ou dados corporativos;
- dumps, volumes, filestore, logs brutos, prompts/respostas não saneados ou banco experimental local;
- o snapshot integral `odoo-19.0`; a reprodução deve usar origem oficial, commit/checksum e digest de imagem.
- o pacote local `relatorio_tcc_I_fci_pacote`; ele contém repositório aninhado, contatos e identificadores acadêmicos, e sua rastreabilidade pública ocorre somente por manifesto saneado de hashes.

Usar variáveis de ambiente ou gerenciador de segredos. Um `.env.example` pode conter somente nomes de variáveis e valores claramente fictícios. Se um segredo for encontrado, não o reproduzir na conversa ou no log: interromper o commit, remover do índice/histórico ainda não publicado, comunicar o responsável e solicitar rotação/revogação.

## Verificação antes de cada commit

Executar:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1
git status --short
git diff --check
git diff --cached --name-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_repository_safety.ps1 -StagedOnly
```

Revisar a lista preparada linha por linha. Arquivos binários gerados podem ser commitados apenas se sua fonte foi validada e o conteúdo de origem não contém segredos ou dados reais.

## Gate de artefatos e dados experimentais

- Desde a v1.2.2, o plano-mestre corrente é publicado somente em Markdown. Não gerar nem preparar novos DOCX/PDF do plano sem nova decisão material.
- O DOCX/PDF do plano e o validador Word da v1.2.1 foram retirados da árvore corrente pela [DEC-025](docs/decision-log.md#dec-025). Seus hashes e o commit de origem permanecem em `docs/releases/v1.2.1.md` e no histórico Git; não restaurá-los ao checkout sem nova decisão. O PDF do artigo em `paper/` é outro artefato e segue seus gates próprios.
- Em uma release do plano, validação, hashes e manifesto devem corresponder à mesma árvore e versão; o resultado `PASS` deve ser obtido antes do staging.
- Se o artigo institucional ou um futuro artefato binário autorizado for gerado, sua fonte deve ser validada na mesma árvore. DOCX deve usar `creator` e `lastModifiedBy` institucionais ou genéricos e não pode conter comentários, alterações controladas, macros, objetos incorporados ou relacionamentos externos não revisados.
- A inspeção visual do artigo institucional ou de futuro PDF autorizado deve cobrir capa, tabelas densas e transições entre capítulos; reprovar página intermediária formada apenas por cabeçalho ou linha residual de tabela.
- `experiments/raw` permanece fora do Git, mas não pode ser descartado. Preservar os dados brutos em armazenamento externo criptografado, com controle de acesso e cópia imutável; versionar no repositório apenas manifesto SHA-256, schema, proveniência, versão e política de retenção sem informações sensíveis.
- Somente datasets e resultados sintéticos saneados podem ser publicados, após revisão por dois integrantes. Cabeçalhos de autorização, prompts ou respostas com credenciais, dumps do Odoo e documentos reais nunca são publicáveis.
- O script local é uma barreira mínima, não uma prova absoluta. Antes de tornar o repositório público, executar também um scanner dedicado de segredos e revisar seus achados sem reproduzir valores sensíveis.

## Regras específicas do artefato

- Odoo principal: 19.0 Community self-hosted, repositório `https://github.com/odoo/odoo.git`, commit fixado `a4b877245c9cb5e3d7152d1593a518170f115ca1`; o branch móvel não atualiza o pin automaticamente.
- A imagem Odoo deve ser construída desse commit; registrar seu digest OCI `sha256:<64-hex>` antes de qualquer run.
- A pasta local `odoo-19.0` é somente para exploração e permanece ignorada.
- JSON-2 é transporte; em C1, a fronteira de autorização é o add-on mínimo e o usuário técnico restrito.
- O LLM propõe; o policy engine autoriza; o executor aplica apenas a decisão autorizada.
- Pagamentos reais, NF-e válida, OCR, SaaS 19.4, módulos Enterprise e IA nativa do Odoo estão fora do escopo.
- Não há participantes humanos; o approval gate técnico (gate de revisão simulado) é avaliado por decisões pré-definidas, sem coleta comportamental.
- O plano-mestre não é o artigo de submissão. O artigo final deve ser criado separadamente sobre cópia saneada do template FCI 2026, com 10–20 páginas incluindo referências e Resumo/Abstract de 150–250 palavras cada.
