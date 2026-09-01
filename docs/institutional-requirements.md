# Matriz de conformidade institucional — TCC II FCI 2026/2

**Status da auditoria:** edital semestral e template de artigo conferidos em 30/08/2026; lacunas residuais identificadas.

**Decisões vinculadas:** DEC-010 / D14 e DEC-011 / D15.

## 1. Escopo e precedência

Esta matriz traduz as exigências recuperadas para o fluxo operacional do grupo. Em caso de divergência, prevalecem a tarefa vigente no Oriente, o edital oficial, o Regulamento Geral de TCC, o Guia Geral de TCC e uma orientação formal da FCI. A divergência deve ser registrada; nenhum requisito será corrigido ou presumido silenciosamente.

O plano-mestre não é o arquivo de submissão. Ele preserva a especificação científica e operacional completa. O produto institucional será um artigo separado, criado sobre uma cópia saneada do template FCI 2026 e limitado a 10–20 páginas.

## 2. Fontes auditadas

| Fonte | Identidade observada | Papel | Estado |
|---|---|---|---|
| `assets/EditalTCC.pdf` | `EditalTCC_2026_2-V1`, 16 páginas, criado em 17/08/2026 | regras e calendário de 2026/2 | auditado |
| `TemplateArtigo_TCC_FCI_2026.doc` | Word legado, quatro páginas | arquivo-base editável do artigo | auditado em modo somente leitura |
| `TemplateArtigo_TCC_FCI_2026.pdf` | criado em 15/08/2026, quatro páginas | referência visual e textual | auditado |
| `src/relatorio_tcc_fci.tex` | fonte histórica do TCC I | continuidade de conteúdo; não é o template TCC II vigente | auditado |
| `src/referencias.bib` | bibliografia histórica do TCC I | insumo a reconciliar; não define automaticamente as referências do artigo novo | auditado por identidade criptográfica |
| `src/AVALIACAO DOS AVALIADORES APÓS APRESENTACO QUE CADASTRARAM NO SISTEMA.txt` | feedback histórico disponível | continuidade e crítica do trabalho; conteúdo bruto permanece local | auditado por identidade criptográfica |

Os hashes, tamanhos, datas e anomalias ficam em `reproducibility/institutional-sources.lock.json`. O pacote local permanece ignorado: contém um repositório Git aninhado, contatos e identificadores acadêmicos. Não preparar o diretório bruto para commit.

O Regulamento Geral de TCC e o Guia Geral de TCC, embora citados pelo edital, não estavam no pacote recebido. A pasta `Latex` do template estava vazia. Portanto, o `.tex` histórico não pode ser declarado compatível com o template 2026 sem adaptação e validação visual.

## 3. Identidade acadêmica confirmada

| Papel | Nome | Estado |
|---|---|---|
| Autor | Felipe Ujvari Gasparino de Sousa | confirmado pelo grupo e pelo fonte do TCC I |
| Autor | Gustavo Nascimento Siqueira | confirmado pelo grupo e pelo fonte do TCC I |
| Autor | Thomaz de Souza Scopel | confirmado pelo grupo e pelo fonte do TCC I |
| Orientador | Mario Olimpio de Menezes | confirmado pelo grupo e pelo fonte do TCC I |

O grupo de três autores atende à regra de dois a quatro estudantes para Ciência da Computação. Permanecem fora do repositório público os contatos e identificadores acadêmicos. Condição PPI/PPP, endereço institucional e demais dados cadastrais do orientador devem ser confirmados diretamente no Oriente antes da submissão.

O cadastro do grupo no Oriente e o requerimento no Portal do Aluno devem ser realizados por **um único integrante designado**, conforme o edital. Conforme DEC-021 e `docs/task-backlog.md`, Gustavo (P3) é o owner operacional de conferir o cadastro/requerimento e preservar os recibos; essa atribuição não significa que a ação externa já tenha sido concluída. O grupo também deverá confirmar com o orientador que o tema está alinhado à sua área ou projeto de pesquisa.

## 4. Requisitos obrigatórios do artigo

| Requisito | Critério de aceite | Evidência esperada |
|---|---|---|
| Modalidade | artigo científico estendido | arquivo final identificado como artigo |
| Extensão | mínimo de 10 e máximo de 20 páginas | contagem do PDF final |
| Alcance do limite | referências incluídas nas 20 páginas | referências terminam até a página 20 |
| Resumo | português, 150–250 palavras; contexto, motivação, objetivo, justificativa, metodologia e resultados | contagem automatizada e checklist semântico |
| Abstract | inglês, 150–250 palavras; equivalência semântica com o Resumo | contagem automatizada, checklist semântico e revisão bilíngue |
| Termos de indexação | Palavras-chave e Keywords | presentes sob os respectivos resumos |
| Estrutura | 1. Introdução; 2. Referencial Teórico; 3. Metodologia; 4. Resultados e discussão; 5. Conclusão; 6. Referências bibliográficas | títulos literais principais no arquivo final |
| Referências bibliográficas | ABNT NBR 6023:2018; somente obras citadas | auditoria bidirecional citação↔referência |
| Formato | template disponibilizado no Oriente | comparação visual e checklist assinado |
| Submissão | tarefa do Oriente entre 03 e 09/11/2026 | recibo de envio preservado |

O edital não informa a extensão de arquivo aceita para o TCC II. Não presumir DOC, DOCX ou PDF: confirmar na tarefa do Oriente e registrar a resposta antes de gerar o pacote de submissão.

## 5. Uso correto do template

O arquivo `.doc` recebido é a autoridade de layout. Não reconstruir o artigo a partir do gerador do plano-mestre e não normalizar estilos indiscriminadamente. A inspeção técnica encontrou A4, uma coluna, corpo predominantemente em Times 12 justificado e espaçamento simples, título centralizado em 16 pontos e seções em 14 pontos. As margens observadas foram aproximadamente 3,25 cm superior, 2,0 cm direita, 2,2 cm inferior e 2,5 cm esquerda. Esses valores são informativos; a cópia do arquivo-base é que preserva a configuração normativa.

O bloco inicial contém título, autores, orientador, afiliações, contatos e ano. Os contatos devem ser inseridos apenas no fonte controlado do artigo, depois de consentimento e conferência; não devem aparecer em logs ou manifests públicos.

O PDF distribuído como template possui título de metadado não relacionado ao TCC e campo de autoria pessoal herdado. A versão final deve reprovar esses metadados, além de comentários, revisões, macros, objetos incorporados e relações externas não revisadas.

## 6. Mapeamento do conteúdo científico para a estrutura oficial

| Seção principal FCI | Conteúdo do projeto |
|---|---|
| Resumo / Abstract | contexto, motivação, problema, lacuna/justificativa, objetivo, metodologia C0/C1, amostra, resultados principais, custo e conclusão limitada |
| 1. Introdução | contexto, prompt injection indireta, problema, público-alvo, RQs, objetivos, contribuições e organização |
| 2. Referencial Teórico | agentes LLM, IPI, defesa em profundidade, ERP/Contas a Pagar e trabalhos correlatos |
| 3. Metodologia | pesquisa aplicada e predominantemente quantitativa, complementada por análise qualitativa de falhas; DSR, experimento controlado, threat model, artefato C0/C1, controles, dataset, protocolo, métricas e análise estatística; declaração de ausência de participantes humanos |
| 4. Resultados e discussão | implementação, resultados RQ1–RQ4, ablações, mecanismos, custo, falhas e ameaças à validade |
| 5. Conclusão | resposta às RQs, contribuições, limites e trabalhos futuros |
| 6. Referências bibliográficas | somente fontes citadas, em conformidade com a NBR 6023:2018 |

Meta editorial: trabalhar para 18–19 páginas, preservando margem para correções da banca. Schemas completos, catálogo de ataques, logs saneados, tabelas extensas e instruções de reprodução ficam no repositório ou material suplementar.

## 7. Calendário oficial e gates internos

| Atividade | Prazo oficial | Gate interno recomendado |
|---|---:|---:|
| Cadastro no Oriente | 18–31/08/2026 | um integrante designado cadastra o grupo, confere os três autores e preserva o recibo |
| Anuência do orientador | até 01/09/2026 | confirmar no dia 01/09 |
| Requerimento no Portal do Aluno | 01–21/09/2026 | o mesmo integrante designado conclui até 07/09, confere os três autores e preserva o recibo |
| Reuniões de orientação | semanais ou quinzenais durante o semestre | agenda recorrente, pauta e registro de presença/encaminhamentos |
| Submissão inicial do artigo | 03–09/11/2026 | arquivo aprovado pelo grupo até 02/11; submeter até 08/11 |
| Indicação dos avaliadores | 03–11/11/2026 | acompanhar com o orientador |
| Divulgação das bancas | até 13/11/2026 | registrar data e sala |
| Banca | calendário consolidado: 16/11–01/12/2026 | confirmar no Oriente devido ao erro de data do edital |
| Artigo corrigido | até 04/12/2026 | revisão do grupo até 03/12 |
| Termo Adelpha, quando aplicável | até 04/12/2026 | decidir publicação com o orientador antes de assinar |
| Anuência final do orientador | até 07/12/2026 | preservar confirmação |

O edital associa o período de 16 a 27/11 a bancas fora do horário de aula e a avaliadores nas condições PPI/PPP. Em outro trecho, associa outros horários e a condição PPA ao intervalo malformado `31/11–01/12`. Como `31/11/2026` é uma data inexistente e o calendário consolidado informa bancas entre 16/11 e 01/12, a janela, os horários e a elegibilidade aplicável dos avaliadores devem ser confirmados conjuntamente no Oriente; este documento não corrige a fonte silenciosamente.

## 8. Apresentação, avaliação e meta de excelência

- apresentação presencial de 15–20 minutos;
- cinco minutos de arguição por avaliador;
- até dez minutos para respostas do grupo;
- duração total da banca de no máximo 50 minutos;
- banca com orientador e dois avaliadores;
- nota ponderada: orientador 40%, avaliador 1 30% e avaliador 2 30%;
- critérios: estrutura, consistência metodológica, embasamento científico, relevância, originalidade, ineditismo, inovação e defesa oral;
- conceito Excelente a partir de 90% de suficiência.

Para conceito Excelente ou Muito Bom, o termo de autorização do Adelpha deve ser entregue até 04/12. O edital exige o termo mesmo quando a publicação não for autorizada, com a opção e a justificativa correspondentes.

## 9. Pendências residuais

- [ ] obter Regulamento Geral e Guia Geral de TCC vigentes;
- [ ] confirmar a extensão aceita pela tarefa de submissão no Oriente;
- [ ] confirmar política institucional para uso e declaração de IA;
- [ ] confirmar janela, horários e elegibilidade dos avaliadores da banca diante do erro `31/11/2026` e das condições PPI/PPP/PPA;
- [ ] confirmar condição PPI/PPP e dados institucionais do orientador;
- [ ] confirmar formalmente o alinhamento do tema à área ou projeto de pesquisa do orientador;
- [x] atribuir papéis P1/P2/P3 nominalmente conforme DEC-021; disponibilidade será revista nos checkpoints semanais;
- [x] designar Gustavo/P3 como único owner operacional do cadastro e requerimento;
- [ ] conferir a conclusão externa do cadastro/requerimento, os três autores e preservar os recibos — evidência parcial de 01/09/2026 mostra o grupo e os três integrantes, com duas confirmações, uma pendência e nenhum recibo visível; captura com identificadores permanece fora do Git e somente seu hash consta em `reproducibility/institutional-evidence.lock.json`;
- [ ] manter orientação semanal ou quinzenal com presença, pauta e encaminhamentos registrados;
- [x] criar fonte separada e editável do artigo, reconstruída e comparada visualmente com o template conforme DEC-019, sem carregar metadados herdados.

## 10. Definition of Done institucional

O artigo só está pronto para a submissão inicial quando:

- possui entre 10 e 20 páginas, incluindo referências;
- Resumo e Abstract têm 150–250 palavras cada e cobrem contexto, motivação, objetivo, justificativa, metodologia e resultados;
- usa literalmente os seis títulos principais exigidos pelo template, incluindo `6. Referências bibliográficas`;
- todas as citações e referências foram reconciliadas sob a NBR 6023:2018;
- autores, orientador, afiliações e contatos foram conferidos;
- metadados, comentários, revisões, macros, objetos e relações externas passaram no gate;
- figuras e tabelas são legíveis na escala de impressão;
- resultados, limitações e claims correspondem aos dados congelados;
- o grupo e o orientador aprovaram o arquivo;
- o alinhamento do tema à área ou projeto de pesquisa do orientador foi confirmado;
- as reuniões semanais ou quinzenais de orientação e a participação do grupo possuem registro;
- a extensão aceita pelo Oriente foi confirmada;
- o recibo de submissão até 09/11/2026 foi preservado.
