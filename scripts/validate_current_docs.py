"""Validate current Markdown navigation and the pre-freeze experimental scope.

No network access. Historical releases and decision bodies are not rewritten.
Run from any directory with: python3 scripts/validate_current_docs.py
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLAN = "Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md"
FILES = (
    PLAN, "AGENTS.md", "README.md", "CHANGELOG.md",
    "docs/decision-log.md", "docs/task-backlog.md", "docs/ai-usage.md",
    "docs/protocol.md",
    "docs/releases/v1.2.12.md", "docs/releases/v1.2.13.md",
    "docs/releases/v1.2.14.md", "docs/releases/v1.2.15.md",
    "docs/releases/v1.2.16.md", "docs/releases/v1.2.17.md", "paper/README.md",
    "paper/SUBMISSION_CHECKLIST.md",
)
LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)")
ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
errors: list[str] = []
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--paper-pdf", type=Path, help="Also inspect a newly compiled article PDF")
parser.add_argument("--paper-log", type=Path, help="Final pdfLaTeX log for this PDF")
parser.add_argument("--report", type=Path, help="Write measured checks as JSON")
args = parser.parse_args()
measurements: dict[str, object] = {}


def prose(text: str) -> list[tuple[int, str]]:
    result = []
    fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("\u0060\u0060\u0060"):
            fence = not fence
            continue
        if not fence:
            result.append((number, line))
    if fence:
        errors.append("Unclosed fenced code block")
    return result


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8-sig")
    result = set(ANCHOR.findall(text))
    seen: dict[str, int] = {}
    for _, line in prose(text):
        match = re.match(r"^#{1,6}\s+(.+)", line)
        if not match:
            continue
        label = LINK.sub(r"\1", match.group(1))
        label = re.sub(r"<[^>]+>", "", label).replace("\u0060", "")
        slug = re.sub(r"[^\w\- ]", "", label.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def validate_markdown(relative: str) -> None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"{relative}: required file absent")
        return
    text = path.read_text(encoding="utf-8-sig")
    explicit = ANCHOR.findall(text)
    if len(explicit) != len(set(explicit)):
        errors.append(f"{relative}: duplicate explicit anchor")
    table_width = None
    for number, line in prose(text):
        # Inline code may contain pipe symbols that do not delimit cells.
        plain = re.sub(r"\u0060[^\u0060]*\u0060", "CODE", line)
        if plain.startswith("|") and plain.rstrip().endswith("|"):
            width = len(re.split(r"(?<!\\)\|", plain)) - 2
            if table_width is None:
                table_width = width
            elif width != table_width:
                errors.append(f"{relative}:{number}: inconsistent table width")
        else:
            table_width = None
        for match in LINK.finditer(plain):
            raw = match.group(2).strip()
            if raw.startswith("<"):
                raw = raw[1:raw.index(">")]
            else:
                raw = raw.split(' "', 1)[0]
            parsed = urlsplit(raw)
            if parsed.scheme or raw.startswith("//"):
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if not target.exists():
                errors.append(f"{relative}:{number}: missing local link target")
            elif parsed.fragment and target.suffix == ".md":
                if unquote(parsed.fragment) not in anchors(target):
                    errors.append(f"{relative}:{number}: missing anchor {parsed.fragment}")


for name in FILES:
    validate_markdown(name)

for obsolete in (
    "Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.docx",
    "Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.pdf",
    "validate_tcc_docx.ps1",
):
    if (ROOT / obsolete).exists():
        errors.append(f"Retired plan artifact still in current tree: {obsolete}")

plan = (ROOT / PLAN).read_text(encoding="utf-8-sig")
# Version history may mention a retired scope, but current specification cannot require it.
current = plan[:plan.index("## Histórico de versões")] + plan[plan.index('<a id="leitura-rapida">'):]
for retired in (r"\bSDR(?:-context|-proposal)?\b", r"\bcanary_origin\b", r"\bSEND_SUPPLIER_MESSAGE\b"):
    if re.search(retired, current):
        errors.append("Current plan still requires a retired exposure artifact")
for ident in ("C03", "C11", "R-POL-08", "I9"):
    if re.search(r"^\| (?:<a[^>]+></a>)?" + ident + r" \|", current, re.M):
        errors.append(f"Retired {ident} still appears in an active definition table")

distribution = current.split("## 12.3 Distribuição do teste v1", 1)[1].split("Dentro de cada família", 1)[0]
pairs = re.findall(r"^\| (A1|A2|A3a) —[^|]+\| (\d+) \| (\d+) \|", distribution, re.M)
if pairs != [("A1", "30", "30"), ("A2", "30", "30"), ("A3a", "30", "30")]:
    errors.append("Final dataset distribution is not 30 pairs per retained objective")
for expected in ("48 × 4 × 3 = 576", "1.224 execuções", "2.016 execuções", "2.448 execuções"):
    if expected not in current:
        errors.append(f"Execution count missing: {expected}")
for value in ("2.160", "2.592", "7.776", "6.480"):
    if value in current:
        errors.append(f"Obsolete total remains: {value}")

tex_files = list((ROOT / "paper/sections").glob("*.tex"))
tex = "\n".join(p.read_text(encoding="utf-8-sig") for p in tex_files)
if re.search(r"\b(?:A3b|SDR|canary_origin|SEND_SUPPLIER_MESSAGE)\b|canário", tex):
    errors.append("Article source still contains the retired exposure evaluation")
targets = re.findall(r"\\hypertarget\{([^}]+)\}", tex)
if len(targets) != len(set(targets)):
    errors.append("Duplicate article reference target")
for target in re.findall(r"\\hyperlink\{([^}]+)\}", tex):
    if target not in targets:
        errors.append(f"Article reference missing target: {target}")

all_tex = "\n".join(p.read_text(encoding="utf-8-sig") for p in (ROOT / "paper").rglob("*.tex"))
paper_sources = "\n".join(
    p.read_text(encoding="utf-8-sig") for p in (ROOT / "paper").rglob("*")
    if p.is_file() and p.suffix in {".tex", ".bib", ".md", ".ps1"}
)
emails = len(re.findall(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", paper_sources, re.I))
measurements["email_addresses_in_versioned_sources"] = emails
if emails:
    errors.append("Article sources contain an email address; inspect privately")
bib = (ROOT / "paper/referencias.bib").read_text(encoding="utf-8-sig")
cites = {key.strip() for group in re.findall(r"\\cite(?:online)?\{([^}]+)\}", all_tex) for key in group.split(",")}
entries = set(re.findall(r"^@\w+\{([^,]+),", bib, re.M))
if cites != entries:
    errors.append("Article citations and bibliography are not bidirectionally consistent")
measurements["citation_keys"] = len(cites)
measurements["bibliography_entries"] = len(entries)
measurements["internal_article_targets"] = len(targets)
for filename, key in (("resumo-pt.tex", "resumo_words"), ("resumo-en.tex", "abstract_words")):
    source = (ROOT / "paper/sections" / filename).read_text(encoding="utf-8-sig")
    source = re.sub(r"%.*", " ", source)
    source = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", " ", source)
    source = re.sub(r"[{}~]|--+", " ", source)
    count = len(re.findall(r"[^\W_]+(?:[-’'][^\W_]+)*", source))
    measurements[key] = count
    if not 150 <= count <= 250:
        errors.append(f"{filename}: abstract outside 150–250 words")

if args.paper_pdf:
    if not args.paper_log:
        errors.append("PDF validation requires its final build log")
    else:
        build_log = args.paper_log.read_text(encoding="utf-8-sig")
        for token, key in (("Overfull", "overfull_boxes"), ("Underfull", "underfull_boxes")):
            measurements[key] = build_log.count(token)
        if measurements["overfull_boxes"]:
            errors.append("Article contains overfull boxes")
        undefined = bool(re.search(r"Citation .+ undefined|There were undefined references|destination with the same identifier", build_log))
        measurements["undefined_citations_or_references"] = int(undefined)
        if undefined:
            errors.append("Article has unresolved or duplicate references")
    try:
        info = subprocess.check_output(["pdfinfo", str(args.paper_pdf)], text=True)
        pdf_text = subprocess.check_output(["pdftotext", "-enc", "UTF-8", "-layout", str(args.paper_pdf), "-"], text=True)
        pages = int(re.search(r"(?m)^Pages:\s+(\d+)", info).group(1))
        measurements["pages"] = pages
        if not 10 <= pages <= 20:
            errors.append("Article outside institutional page limit")
        for required in (r"(?m)^Encrypted:\s+no$", r"(?m)^JavaScript:\s+no$", r"(?m)^Page size:.*\(A4\)"):
            if not re.search(required, info):
                errors.append("Article fails format or PDF safety check")
        if not re.search(r"(?m)^Creator:\s+Universidade Presbiteriana Mackenzie", info):
            errors.append("Article creator metadata is not institutional")
        ascii_info = "".join(c for c in unicodedata.normalize("NFD", info) if not unicodedata.combining(c))
        title = re.search(r"(?m)^Title:\s+(.+?)\s*$", ascii_info)
        expected_title = "Desenvolvimento e implementacao de uma arquitetura de protecao na integracao de LLMs em ERPs: estudo de caso com Odoo e Contas a Pagar"
        if not title or title.group(1) != expected_title:
            errors.append("Article title metadata does not match the adopted title")
        inherited = bool(re.search(r"Milton|Vestibular|Nome Aluno|aluno\.um", info, re.I))
        measurements["inherited_template_metadata"] = inherited
        if inherited:
            errors.append("Article contains inherited template metadata")
        ascii_text = "".join(c for c in unicodedata.normalize("NFD", pdf_text) if not unicodedata.combining(c))
        for heading in ("1. Introducao", "2. Referencial Teorico", "3. Metodologia", "4. Resultados e discussao", "5. Conclusao", "6. Referencias bibliograficas"):
            if heading not in ascii_text:
                errors.append("Article missing a required institutional heading")
        measurements["required_main_headings"] = 6
        placeholders = len(re.findall(r"(?i:Nome Aluno|INSERT(?:IR)? RESULT|PLACEHOLDER|aluno\.um)|\bTODO\b|\bFIXME\b|\[REDACTED", pdf_text))
        measurements["forbidden_placeholders"] = placeholders
        if placeholders:
            errors.append("Article contains an unresolved placeholder")
        if re.search(r"\bA3b\b|\bSDR\b|canário|canary_origin", pdf_text):
            errors.append("Compiled article still contains retired scope")
        page_words = [len(page.split()) for page in pdf_text.split("\f") if page.strip()]
        measurements["page_word_counts"] = page_words
        if any(count < 40 for count in page_words[1:-1]):
            errors.append("Potential intermediate header-only page; inspect layout")
        measurements["pdf_text_and_metadata"] = "PASS"
    except (OSError, subprocess.CalledProcessError):
        errors.append("Could not inspect PDF with pdfinfo/pdftotext")

# Protect the contents of already recorded decisions; added anchors are navigation only.
try:
    old = subprocess.check_output(
        ["git", "show", "HEAD:docs/decision-log.md"], cwd=ROOT, text=True, encoding="utf-8"
    )
    now = (ROOT / "docs/decision-log.md").read_text(encoding="utf-8-sig")
    def decision_bodies(text: str) -> dict[str, str]:
        text = re.sub(r'<a id="dec-\d+"></a>\n\n', "", text)
        blocks = re.split(r"(?m)^## (DEC-\d{3}) —", text)
        return {blocks[i]: blocks[i + 1].strip() for i in range(1, len(blocks), 2)}
    old_bodies = decision_bodies(old)
    now_bodies = decision_bodies(now)
    for ident, body in old_bodies.items():
        if ident != "DEC-023" and now_bodies.get(ident) != body:
            errors.append(f"Historical decision body changed: {ident}")
except subprocess.CalledProcessError:
    errors.append("Could not verify historical decisions against Git")

if errors:
    print("Current documentation validation: FAIL")
    for error in errors:
        print("- " + error)
    raise SystemExit(1)
if args.report:
    args.report.write_text(json.dumps({"status": "PASS", **measurements}, ensure_ascii=False, indent=2) + "\n")
print(f"Current documentation validation: PASS ({len(FILES)} Markdown files)")
print("Links, anchors, tables, retained scope, matrices, article references and historical decisions checked.")
