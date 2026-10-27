# Revisão independente do piloto concluído — 27/10/2026

**Escopo:** execução `fc6da3e17e5c475fb1c072d1894f3d64`, [resultado publicado](../pilot-state-resultado.md) e [fechamento (DEC-099)](../decision-log.md#dec-099). Revisores: agentes Codex `audit_pilot_completion` e `audit_pilot_analysis`, distintos dos autores da execução e da adaptação do analisador; família GPT-6, variante/backend não expostos. Base documental `9f6c5ec`. Revisão automatizada, sem assinatura humana ou congelamento retroativo.

## Execução e integridade

**PASS, sem bloqueante e sem indicação de repetir a coleta.** O auditor reprocessou 144 envelopes pelos parsers: 95 CREATE, 48 POST e um sem proposta válida. Validou 576 capturas e 144 restaurações, identidade, aprovação, supervisão e oráculo recalculado; nenhuma divergência. Conferiu 144 IDs/slots únicos, posições 1–144, 24 membros × duas condições × três repetições, ordem e semente `2026102701`. Os 158 arquivos do bundle coincidem com o snapshot e a árvore revista. Em cada um dos 24 grupos, os seis corpos de requisição são idênticos entre condições/repetições e vinculados aos registros.

Os 144 históricos têm uma tentativa. Nos 143 retornos válidos: `deepseek-flash`, temperatura 0, thinking desligado, limite de saída 2048. O erro restante é `invalid_schema`, mantido como execução avaliável sem proposta. Quatro adulterações de oráculo/reset com hash do registro recalculado foram rejeitadas nos caminhos CREATE e POST. Consulta Docker somente leitura confirmou zero contêineres, volumes e redes restantes do UUID. A ausência de segredo é o resultado registrado pelo scanner do produtor; não se afirma nova varredura independente de credenciais.

## Análise e conclusões

O segundo auditor cruzou os 144 oráculos resumidos com os registros e reexecutou o analisador: 144 avaliáveis, nenhuma ausência; BTSR C0 36/36 e C1 35/36; ASR-state e proposta comprometida 0/36 por condição; UACR 0/12 por condição; utilidade sob ataque 36/36 por condição. C1 teve 47 ALLOW, 24 REVIEW_REQUIRED e um slot sem decisão por ausência de proposta. Tokens conferidos: 171.751 de entrada, 44.635 de saída, total 216.386. API: mediana 2,27746 s, máximo 3,25997 s.

O BCa foi recalculado por implementação independente em memória, a partir dos registros: onze pares com diferença zero e um com −1/3; diferença total −1/36, IC95% BCa [−13,8889; 0] pontos percentuais e percentil [−8,3333; 0]. Limites conservadores também coincidem: ASR ±78,4100 pontos; UACR [−100; 100]. Passaram 34 testes existentes e oito contraprovas independentes de filtros, elegibilidade A3a, slot incompleto, universo vazio, fronteira, pesos desiguais, ordem/semente e não estimabilidade. As repetições continuam agrupadas por par.

**Parecer:** liberar `AGENT_REVIEWED` para RUN-01/02/06/09, PILOT-01/03, execução de PILOT-02 e cálculos de AN-01–04; STAT-01 agora inclui a adaptação descritiva. A competência C0 foi medida (36/36). Custódia, figuras, preço/faturamento, publicação de exports e aceite do artigo continuam separados. Nenhuma defesa foi exercitada contra proposta comprometida; não se demonstrou redução de ataques ou equivalência de segurança. A diferença de utilidade observada não deve ser atribuída causalmente a um bloqueio C1: a perda foi erro de formato do modelo. Limites binomiais que supõem repetições independentes são ilustrativos, sem substituir o resumo por cenário ou o contraste por execução.

## Proveniência e preservação

| Artefato | SHA-256 / commit |
|---|---|
| Evidência do lote | `2d2f06a670e1d04cfde9aaed04a702cb1c3d9c84b130a5935c794e6c5994ba06` |
| Bundle de fontes | `5634ce68d735fa5e50a06cb07e2073ecd0e911bbfb34aa40f41d9b6c4eace5ee` |
| Agenda | `63cee27ce1b4f58456b5ce44274b57560973b1e761764eed837752ecc14c2165` |
| Coorte `.4` | `cd3ff7b73c7d2f61b307ac89edc44387131704cf2bae28317087c3c5f64966f5` |
| Base da execução | `c6f95eccfea823b29a450941925f48f70450f780` |
| Analisador revisto | `351ee9abe3c2c0b2cd04096cb7c1176364e5fdf6e2aa599367a3b13cc5ad0f4f` |
| Componente matemático | `a122ca60a1e966e2c43245d41cb5e6e5dc8244fd87382bb53807cb7ce398974a` |

As auditorias foram somente leitura, sem API, nova coleta ou mutação Docker. Dados brutos, tentativa parcial anterior e `scientific_run=false` foram preservados. A revisão de custódia e sua conclusão são registradas na DEC-099; só se declara cópia válida após restauração efetivamente verificada. As limitações de revisão por IA permanecem no artigo.

## Artigo: correções materiais ainda necessárias

O revisor conferiu os rascunhos não commitados, sem editá-los ou gerar PDF. Além de preencher os resultados do Odoo, corrigir:

- `03-metodologia.tex:181` e `04-resultados.tex:77`: houve chamada nova ao modelo em cada slot (DEC-095), sem reutilizar propostas da rodada 2.
- `03-metodologia.tex:105`: o envelope/prompt de conteúdo não confiável foi comum a C0 e C1, não proteção exclusiva de C1.
- `03-metodologia.tex:183`: a agenda foi um embaralhamento global de 144 slots; retry de observação de três leituras não foi integrado. Captura/efeito ERP incerto interrompe; só a incerteza do provedor sem proposta recebe a exceção DEC-096.
- `03-metodologia.tex:185`: a análise descritiva realizada não publica McNemar; retirar essa promessa.
- `03-metodologia.tex:124`: não alegar cópia imutável; o destino autorizado é local, DPAPI CurrentUser, com suas limitações.

Instantâneo revisado: metodologia SHA-256 `b59113ef70c2f1b33b9ef282f311371f0bd32556ad6654b457f81899cc786ef3`; resultados `0f1e70070cf1fd1e93548f3f082449fab915241a9a69960e9283ff944598dfd9`. As fontes podem avançar na outra sessão; conferir o estado antes de aplicar. Esses ajustes não exigem repetir a coleta e não representam aceite do PDF corrente.

## Custódia concluída

A cópia local `b9a2d1004fb04c6da9a316a331564608` terminou com PASS: 20.678 arquivos, 370.323.575 bytes originais, restauração verificada e originais inalterados. O integrador reconferiu contagens/flags e hashes do arquivo cifrado e manifesto. SHA-256 cifrado: `6913e545e80b40c5c04a5eb5e4291ba79513a1778134bc9c4e17ecd08b806164`; manifesto privado: `c360d758ae5fa53c1708a8d13f5a0779840fdadf516103b61e745604a9720553`. Destino `.runtime/custody`, DPAPI CurrentUser, local/não portátil, sem imutabilidade ou proteção externa. Brutos e manifesto detalhado permanecem fora do Git. Não houve nova coleta ou descarte da tentativa parcial anterior.

O utilitário no hash `1c2be3ccdf03c0c9de9cbf7a1a0e1b6de5f873914682f2ecc6213be3c317960c` passou em revisão distinta: oito ZIPs sintéticos, quatro comparações de seleção e 28 verificações existentes, além da cópia/restauração real. O teto foi ampliado para 512 MiB e a busca de nomes passou a índice Ordinal; criptografia, formato, exclusividade e validação de bytes foram preservados.
