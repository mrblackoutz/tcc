# Revisão estruturada da literatura — protocolo e matriz

**Estado:** protocolo em redação; execução não iniciada. **Tarefas:** SCI-05 (protocolo),
SCI-06 (execução), SCI-07 (formulação da lacuna). **Gate:** G1, replanejado para 13/09/2026.

Este arquivo é o esqueleto normativo exigido por §29 do plano-mestre. Ele é pré-condição da
afirmação de lacuna de §4.2: até que a matriz esteja encerrada, o artigo usa "há evidência
limitada" ou "não foram identificados estudos que combinem", acompanhado do protocolo de
busca, e a palavra "primeiro" não é usada.

## 1. Fontes

Conforme §29.1: ACM Digital Library; IEEE Xplore; Scopus ou Web of Science conforme acesso;
ACL Anthology; Google Scholar para snowballing; arXiv apenas com status de preprint
explicitado; OWASP, NIST, MITRE e Odoo como fontes normativas, nunca como prova experimental.

## 2. Parâmetros de auditabilidade

Estes parâmetros faltavam ao protocolo e foram exigidos pelo achado LIT-04 da revisão
independente. Sem eles a revisão não é reproduzível.

| Parâmetro | Definição |
|---|---|
| Revisores de triagem | dois, independentes, sobre título e resumo |
| Resolução de divergência | terceiro integrante decide; a divergência fica registrada, não é apagada |
| Janela temporal | publicações de 2022 em diante para ataque e defesa; sem limite inferior para fundamentação clássica |
| Data da última busca | a registrar; será repetida na semana anterior à submissão |
| Critério de parada da busca ampla | saturação: duas páginas consecutivas de resultados ordenados por relevância sem nenhum registro novo elegível |
| Reporte do fluxo | contagens de recuperados, deduplicados, excluídos por etapa e incluídos, com os motivos de exclusão |

## 3. String de busca

A string de §29.2 permanece a base. O achado LIT-04 registrou que ela não recupera a linha
de 2026 sobre controle de autoridade em tempo de execução, porque esses trabalhos não usam
os termos de domínio. Fica acrescentada uma segunda string, sem o bloco de domínio e com o
vocabulário mais recente, cujos resultados entram na mesma matriz:

```text
("indirect prompt injection" OR "prompt injection" OR "agent hijacking"
 OR "authority confusion")
AND
(agent OR "tool-integrated" OR "tool-using" OR "action-time authorization"
 OR "policy gate" OR "least privilege")
```

## 4. Matriz de extração

Uma linha por trabalho, com os campos de §29.5: referência; threat model; ambiente; defesa;
dados; métricas; resultado; reprodução; e lacuna específica para este TCC, sem linguagem
promocional.

| Referência | Threat model | Ambiente | Defesa | Dados | Métricas | Resultado | Reprodução | Lacuna para o TCC |
|---|---|---|---|---|---|---|---|---|
| *a preencher em SCI-06* | | | | | | | | |

## 5. Contraexemplos a confirmar

A revisão independente localizou indícios de trabalhos de 2026 que cobrem isoladamente
parte das sete cláusulas da lacuna de §4.2, entre eles benchmarks de autorização em
integrações empresariais e gates de política sensíveis a metadados. Esses indícios **não
foram confirmados** de forma independente e estão registrados como achado LIT-03 em
`docs/revisao-independente-v1.2.9.md`. Confirmá-los ou refutá-los é parte de SCI-06. Se
algum se confirmar equivalente, aplica-se a mitigação de R20: enquadrar o trabalho como
replicação, extensão ou avaliação comparativa, e retirar qualquer claim de ineditismo.

## 6. Fundamentação clássica

Obtida por busca dirigida, não sistemática, conforme §29.1.1. Não entra nesta matriz
comparativa e não sustenta claim de resultado.
