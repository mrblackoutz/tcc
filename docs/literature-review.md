# Revisão dirigida da literatura — registro e matriz crítica

**Estado em 17/10/2026:** procedimento replanejado; busca e matriz ainda não concluídas. **Tarefas:** SCI-05 (procedimento), SCI-06 (verificação e matriz), SCI-07 (lacuna). O [corte aprovado (DEC-058)](decision-log.md#dec-058) substitui a promessa de revisão sistemática/estruturada abrangente por revisão dirigida e transparente, conforme [plano §29](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#sec-29).

A revisão sustenta o problema e compara o artefato com trabalhos efetivamente verificados. Não promete exaustividade, saturação ou cobertura de todas as bases. A lacuna só será formulada após examinar a matriz; não usar “primeiro” nem confundir ausência de trabalho localizado com prova de inexistência.

## 1. Fontes e recorte

Priorizar artigos e artefatos primários sobre prompt injection indireta, agentes com ferramentas, autorização em tempo de execução, isolamento de privilégios e avaliação de segurança/utilidade. Consultar, conforme acesso e relevância, ACL Anthology, ACM Digital Library, IEEE Xplore e repositórios oficiais dos trabalhos. Google Scholar e referências dos artigos podem apoiar descoberta e encadeamento de referências (*snowballing*). Scopus/Web of Science são opcionais, não compromisso de cobertura.

arXiv é admissível com status de preprint explícito. OWASP, NIST, MITRE e documentação oficial Odoo fundamentam terminologia, requisitos e funcionamento; não são prova experimental de eficácia de C1. A literatura clássica de segurança e método pode ter qualquer data; para ataques/defesas atuais, priorizar 2022 em diante sem excluir precedente conceitual pertinente.

## 2. Registro mínimo de seleção e verificação

Cada busca ou descoberta efetivamente realizada terá data, fonte, consulta ou referência de origem, itens consultados e critério de escolha/descarte. Não preencher contagens, buscas ou datas por estimativa. Registrar indisponibilidade de texto/artefato e não atribuir resultados ao que não foi lido.

| Campo | Registro exigido |
|---|---|
| Origem | base, página oficial ou referência de outro trabalho; URL/DOI |
| Consulta e data | expressão ou motivo da descoberta; data real de acesso |
| Escolha/descarte | relação com threat model, método ou comparação; justificativa breve |
| Verificação | fonte primária e versão lidas; código/dados acessíveis ou não |
| Revisão | integrante responsável e conferência independente das alegações usadas no artigo |
| Atualização | nova verificação dirigida de trabalhos recentes antes de fechar o artigo |

Não há triagem sistemática obrigatória de todos os títulos, fluxo de saturação ou meta de quantidade de artigos. Permanecem a revisão crítica, a rastreabilidade e a resolução documentada de divergências. Revisão dirigida da literatura não reduz a revisão independente de **cada cenário** do ground truth.

## 3. Consultas orientadoras

Executar apenas as consultas úteis ao recorte e registrar o que de fato for usado; os exemplos não indicam buscas já realizadas:

```text
("indirect prompt injection" OR "prompt injection")
AND (agent OR "tool-using")
AND (ERP OR invoice OR "accounts payable" OR "enterprise workflow")

("prompt injection" OR "agent hijacking" OR "authority confusion")
AND ("action-time authorization" OR "policy gate" OR "least privilege")
```

Complementar por referências de benchmarks/defesas identificados e buscar contraexemplos à lacuna. Incluir ataque, defesa ou benchmark com interação com conteúdo externo/ferramentas, método suficientemente descrito e versão primária verificável. Não usar publicidade, duplicatas ou jailbreak sem relação com o recorte como evidência de eficácia.

## 4. Matriz crítica

Uma linha por trabalho verificado, com resultados e limites atribuídos à fonte correta. A quantidade deriva das evidências relevantes, não de meta artificial.

| Referência e origem/data | Threat model | Ambiente | Defesa | Dados | Métricas | Resultado e limites | Reprodução | Diferença específica para o TCC |
|---|---|---|---|---|---|---|---|---|
| *A preencher em SCI-06; nenhuma comparação concluída nesta revisão do procedimento.* | | | | | | | | |

## 5. Contraexemplos e formulação da lacuna

A [revisão independente histórica](revisao-independente-v1.2.9.md) apontou indícios de trabalhos de 2026 sobre autorização em integrações empresariais e gates sensíveis a metadados (LIT-03/LIT-04). Esses indícios **ainda exigem confirmação primária** em SCI-06. Se um trabalho já cobrir a combinação relevante, enquadrar o TCC como replicação, extensão ou avaliação contextualizada; não preservar ineditismo por conveniência.

A afirmação de lacuna deverá indicar o que foi efetivamente consultado, a diferença de tarefa/ambiente/threat model/oráculo e os limites da revisão dirigida. A entrega avalia um modelo e o pacote C1 completo; não promete transportabilidade entre modelos, defesa contra ataques adaptativos ou causalidade por camada.

## 6. Fundamentação clássica e fechamento

Obras clássicas são selecionadas pela relação com um princípio concreto do artefato ou com o método, sem limite temporal inferior e sem apresentá-las como prova de resistência a ataques. Conferir autoria, edição, URL/DOI e a frase sustentada antes de citar.

SCI-05 conclui com procedimento revisado; SCI-06, com registro real e matriz crítica conferida; SCI-07, com lacuna e claims proporcionais às fontes. Nenhuma dessas tarefas é concluída somente pela criação deste arquivo.
