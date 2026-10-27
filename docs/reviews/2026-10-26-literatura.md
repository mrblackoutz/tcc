# Verificação dirigida de literatura e margem de utilidade

**Data:** 26/10/2026. **Base consultada:** `bc19c7e46151a0819a548d4e25579b5ba710a0f2`, mais alterações documentais identificadas abaixo. **Autor/verificador:** agente Codex `review_c0_data`, família GPT-6; variante/backend não expostos. A [DEC-092](../decision-log.md#dec-092) antecedeu a edição. Revisão automatizada, sem assinatura em nome dos integrantes.

## Literatura — SCI-05/06/07/10

A [revisão dirigida](../literature-review.md) contém consultas efetivamente realizadas, dez comparadores na matriz crítica (§4) com versões/fontes primárias (incluindo Greshake 2023 e Zhan et al. 2025), quatro contraexemplos de 2026 (§5) e a conferência das vinte entradas citadas no artigo (§6). Foram examinados métodos e limites dos comparadores da matriz; nos três contraexemplos adicionais fora da matriz principal, conferiram-se metadados e resumo. Repositórios acessíveis não foram executados; livros e artigos de método tiveram verificação parcial explicitada. Não se promete exaustividade.

O cruzamento entre `paper/referencias.bib` e as citações dos arquivos TeX produziu 20 entradas/20 chaves distintas, zero ausentes e zero sem uso. Não foi identificada referência inexistente. Datas históricas de acesso não foram reescritas. Páginas DeepSeek são móveis; não comprovam o backend de uma chamada histórica. As páginas Odoo foram recuperadas pela busca oficial após timeout da abertura direta. A data online de Peffers difere do ano do volume, sem invalidar o ano bibliográfico de 2007.

A contribuição foi delimitada à avaliação contextualizada de Contas a Pagar/Odoo e seus efeitos observados. AgentDojo já verifica estado; CaMeL, DRIFT e os trabalhos recentes já tratam separação de autoridade/gates. Portanto, não se sustenta novidade genérica desses mecanismos nem ausência de estudos empresariais. CaMeL e os preprints recentes não estão nas vinte entradas atuais: se o artigo incorporar suas alegações, deve incluir suas referências.

**Encaminhamento:** SCI-05/06/07/10 estão implementadas documentalmente e prontas para conferência por agente distinto/integrador. Este autor não concede a si próprio `AGENT_REVIEWED` pela matriz que escreveu. O integrador pode conceder esse estado após conferir fontes/alegações; aprovação nominal do grupo e reconciliação final das frases do artigo continuam próprias. Não há aceite de freeze ou conclusão sobre eficácia.

SHA-256 dos artefatos conferidos: revisão dirigida `7b495c8d67c0488581bf53e674cd9ff5e5968ac4feec0978dd8eee2649b2b7ed` (versão inicial Codex `485a796f6f8719039a7724c1cf79a37606b2f40cbae71e54065b42e86bb92e5d`); bibliografia `9e448f74bee367e5536ea4fb14772d3c4207f22b7d85895444fa73cb7648e1a3`.

## SCI-02 — justificativa da margem já fixada

Foi revisado somente o parágrafo **“Justificativa da margem de utilidade — SCI-02”** no prefixo vigente do protocolo. A interpretação está correta: dez pontos percentuais de BTSR representam dez tarefas benignas adicionais não concluídas a cada cem em comparação com C0, em diferença absoluta. Por exemplo, 90% versus 80% são −10 pontos percentuais e perda relativa de aproximadamente 11,1%; as duas medidas não são intercambiáveis.

A justificativa é uma tolerância de projeto, sem alegar validação empresarial, coleta com participantes ou estimativa orientada pelo piloto. A regra inferencial preserva limite inferior do IC95% **estritamente maior** que −0,10; igualdade ou estimativa pontual favorável não bastam. Não foi introduzido novo limiar nem alterada a sequência de hipóteses. **Parecer: recomenda `AGENT_REVIEWED` para esse racional**, independente da ratificação nominal antes do freeze. Nenhuma taxa experimental foi usada para avaliar o parágrafo.

Este trabalho não abriu outputs da rodada 2 ou conjunto final, não fez chamadas ao modelo e não alterou dados, prompts, defesa, bibliografia, protocolo ou artigo. A validação é documental; nenhuma suíte de testes de execução foi repetida para sustentar mudança de texto.

Validação corrente: PASS nos vinte Markdown do validador do projeto e nos três pareceres/documentos desta revisão, incluindo links, âncoras e tabelas; verificação de segurança do repositório PASS. Nenhum arquivo foi preparado para commit por este agente.

## Conferência independente pelo integrador

O integrador, distinto do autor do levantamento, reexecutou o cruzamento completo BibTeX/citações: 20/20, sem ausência ou órfã, bibliografia inalterada. Reabriu as fontes primárias de AgentDojo, TaskShield, StruQ, CaMeL, NetInjectBench e AgentRedBench. Conferiu o contraexemplo central nas seções 3.1/3.4 de AgentDojo: já existem verificadores formais de utilidade/segurança apoiados no estado; também há precedente explícito de gate de política e integridade dos metadados no resumo de NetInjectBench v2. Isso sustenta a formulação contextual e impede claims genéricos de ineditismo.

Parecer: SCI-05/06/07/10 podem ficar `AGENT_REVIEWED` para o procedimento, matriz, formulação candidata e correspondência bibliográfica. Essa conferência amostral não declara reprodução dos estudos, leitura integral dos livros fechados nem checagem definitiva de cada frase do artigo final. Assinaturas nominais e revisão da versão final do artigo permanecem gates próprios. Nenhum resultado da rodada 2 foi aberto para este parecer.

## Atualização de escopo — 27/10/2026

O parecer acima preserva o escopo e os hashes efetivamente revistos em 26/10. O [estudo descritivo adotado (DEC-094)](../decision-log.md#dec-094) e a [reconciliação corrente (DEC-097)](../decision-log.md#dec-097) substituem as cobranças confirmatórias, o corpus adicional e a proposta antes pendente. Permanecem válidas as provas de componentes, contratos, matemática, segurança e preparo. A coleta vigente tem 144 execuções; revisão do lote, intervalos aplicados e aceite do artigo continuam separados. Não se atribui à revisão antiga cobertura da implementação integrada posterior.
