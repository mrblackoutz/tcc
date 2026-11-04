# Varredura de segredos e dados pessoais antes de tornar o repositório público (04/11/2026)

O [AGENTS.md](../../AGENTS.md) exige um scanner dedicado de segredos antes de o repositório ficar público, além da checagem local `scripts/check_repository_safety.ps1`. Esta página registra o que foi feito, sem reproduzir nenhum valor.

## Como foi feito

- **Scanner:** gitleaks 8.30.1, baixado da página oficial de releases no GitHub com autorização de Gustavo. O checksum SHA-256 do arquivo conferiu com o publicado pelo projeto.
- **Alcance:** os 162 commits de todas as branches locais e remotas (`--log-opts=--all`), com os valores mascarados no relatório (`--redact=100`).
- **Busca complementar:** varredura própria do histórico atrás de RAs, CPF, telefones, e-mails, tokens conhecidos e caminhos pessoais, mostrando só contagens e arquivos.

## Resultado no histórico do Git

| Achado | Quantidade | Conclusão |
|---|---:|---|
| `sumologic-access-token` em `paper/validation-report.json` | 12 | Falso positivo. São os hashes SHA-256 dos arquivos `resumo-pt.tex` e `resumo-en.tex`; a regra dispara pela palavra "sumo" dentro de "resumo". |
| `generic-api-key` em um teste e no cliente simulado do modelo | 4 | Falso positivo. São chaves fictícias escritas `synthetic-…`. |
| RAs, CPF, telefones, tokens reais, chaves privadas e caminhos pessoais | 0 | Nada encontrado no conteúdo. |
| E-mails reais no conteúdo | 0 | Nada encontrado; os candidatos eram decoradores `@pytest…`. |

O arquivo [`.gitleaks.toml`](../../.gitleaks.toml) usa as regras padrão e só duas exceções estreitas:

- hashes de 64 caracteres hexadecimais dentro de `paper/validation-report.json`;
- valores que começam com `synthetic`.

Com ele, a varredura do histórico termina com **0 achados**.

## O que não é conteúdo, mas fica visível com o repositório público

- **E-mails nos commits:** nove commits de 07 e 08/09/2026 levavam endereços reais nos metadados de autor, um corporativo e um pessoal. Em 04/11 o histórico foi reescrito só nesses metadados ([DEC-101](../decision-log.md#dec-101)): agora todos os commits usam o endereço genérico, e o [mapa de commits](../../reproducibility/commit-map-2026-11-04.json) liga os identificadores antigos aos novos.
- **Nomes:** os nomes dos autores e do orientador aparecem no artigo, no README e nos documentos do grupo.

## Pasta de trabalho fora do Git

A varredura da pasta inteira encontrou credenciais locais e descartáveis do laboratório apenas em lugares que o Git não versiona:

- `.runtime/`;
- `odoo-19.0/`, com as chaves de teste do próprio Odoo;
- `.env`;
- `.claude/`, que guarda um *worktree* antigo de outra sessão.

A `.claude/` não era ignorada e passou a constar no `.gitignore`. Nenhum desses arquivos está no histórico.

## Repetir a varredura

```bash
gitleaks git . --log-opts="--all" --redact=100 --config .gitleaks.toml
```
