#!/usr/bin/env bash
# Builds the submission PDF: the final article followed by the AI-use
# declaration (Anexo I) as an annex. The annex does not count toward the
# 20-page limit. Outputs go to .runtime/submission/ and never into paper/,
# because the declaration carries student IDs and an e-mail address.
#
# Two modes, chosen by the declaration given:
# - unsigned declaration: builds relatorio_tcc_ii_para_assinatura.pdf, the single
#   file that authors and advisor then sign with gov.br; check the signed copy
#   with paper/check_signed_submission.sh;
# - declaration already signed: the gov.br stamps are PDF annotations, which
#   pdfpages would drop, so the annex is first flattened with pdftocairo; the copy
#   keeps the visible stamps but not the cryptographic validation, which stays
#   with the original signed file.
# Usage, from the repository root in WSL/Linux with TeX Live and Poppler:
#   bash paper/build_submission.sh <declaration.pdf>
set -euo pipefail

annex_arg="${1:?usage: bash paper/build_submission.sh <declaration.pdf>}"
root="$(cd "$(dirname "$0")/.." && pwd)"
annex="$(cd "$(dirname "$annex_arg")" && pwd)/$(basename "$annex_arg")"
out="$root/.runtime/paper-submission"

# Count only; signer identities are not printed because certificates may carry a CPF.
signatures="$(pdfsig "$annex" 2>/dev/null | grep -c '^Signature #' || true)"
valid="$(pdfsig "$annex" 2>/dev/null | grep -c 'Signature is Valid' || true)"
if [ "$valid" -ne "$signatures" ]; then
  echo "The declaration has invalid digital signatures: $valid valid of $signatures" >&2
  exit 1
fi

rm -rf "$out"
mkdir -p "$out" "$root/.runtime/submission"
if [ "$signatures" -eq 0 ]; then
  dest="$root/.runtime/submission/relatorio_tcc_ii_para_assinatura.pdf"
  cp "$annex" "$out/annex.pdf"
else
  dest="$root/.runtime/submission/relatorio_tcc_ii_submissao.pdf"
  pdftocairo -pdf "$annex" "$out/annex.pdf"
fi
annex_pages="$(pdfinfo "$out/annex.pdf" | awk '/^Pages:/ {print $2}')"

cd "$root/paper"
compile() {
  pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error \
    -output-directory="$out" -jobname=main "\def\tccfinal{}\def\tccannex{$out/annex.pdf}\input{main.tex}" >/dev/null
}
compile
(cd "$out" && BIBINPUTS="$root/paper:" bibtex main >/dev/null)
compile
compile
compile

cd "$root"
python3 scripts/validate_current_docs.py --paper-pdf "$out/main.pdf" --paper-log "$out/main.log" \
  --paper-annex-pages "$annex_pages" --report "$out/checks.json"
total_pages="$(pdfinfo "$out/main.pdf" | awk '/^Pages:/ {print $2}')"
pdftoppm -r 60 -png -singlefile -f "$total_pages" -l "$total_pages" "$out/main.pdf" "$out/annex-last-page"
cp "$out/main.pdf" "$dest"
echo "PDF: $dest"
echo "Pages: $total_pages ($annex_pages of annex); digital signatures in the declaration: $valid"
echo "Last page for a visual check: $out/annex-last-page.png"
sha256sum "$dest"
