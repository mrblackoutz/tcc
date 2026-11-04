#!/usr/bin/env bash
# Checks the single submission PDF after authors and advisor signed it with gov.br.
# The signer rewrites the file, so the check compares content, not bytes:
# - every digital signature is intact and at least the expected number exist;
# - the page count matches the unsigned file validated by build_submission.sh;
# - the article pages have exactly the same text;
# - every original line of the declaration pages is still there, in order
#   (signature stamps may add lines).
# Signer identities are never printed, because certificates may carry a CPF.
# Usage, from the repository root in WSL/Linux with Poppler and Python 3:
#   bash paper/check_signed_submission.sh <signed.pdf> [expected-signatures, default 4]
set -euo pipefail

signed_arg="${1:?usage: bash paper/check_signed_submission.sh <signed.pdf> [expected-signatures]}"
expected="${2:-4}"
root="$(cd "$(dirname "$0")/.." && pwd)"
signed="$(cd "$(dirname "$signed_arg")" && pwd)/$(basename "$signed_arg")"
unsigned="$root/.runtime/submission/relatorio_tcc_ii_para_assinatura.pdf"
annex="$root/.runtime/paper-submission/annex.pdf"
dest="$root/.runtime/submission/relatorio_tcc_ii_submissao.pdf"

if [ ! -f "$unsigned" ] || [ ! -f "$annex" ]; then
  echo "Unsigned build not found; run paper/build_submission.sh with the unsigned declaration first" >&2
  exit 1
fi

signatures="$(pdfsig "$signed" 2>/dev/null | grep -c '^Signature #' || true)"
valid="$(pdfsig "$signed" 2>/dev/null | grep -c 'Signature is Valid' || true)"
if [ "$signatures" -lt "$expected" ] || [ "$valid" -ne "$signatures" ]; then
  echo "Expected at least $expected intact signatures; found $valid intact of $signatures" >&2
  exit 1
fi

annex_pages="$(pdfinfo "$annex" | awk '/^Pages:/ {print $2}')"
python3 - "$signed" "$unsigned" "$annex_pages" <<'PY'
import subprocess
import sys

signed, unsigned, annex_pages = sys.argv[1], sys.argv[2], int(sys.argv[3])


def pages(path):
    text = subprocess.check_output(["pdftotext", "-layout", path, "-"], text=True)
    parts = text.split("\f")
    return parts[:-1] if parts and not parts[-1].strip() else parts


new, old = pages(signed), pages(unsigned)
if len(new) != len(old):
    sys.exit(f"Page count changed: {len(new)} signed, {len(old)} unsigned")
article = len(old) - annex_pages
for number in range(article):
    if new[number] != old[number]:
        sys.exit(f"Article page {number + 1} differs from the validated build")
for number in range(article, len(old)):
    remaining = iter(line.strip() for line in new[number].splitlines() if line.strip())
    for line in (line.strip() for line in old[number].splitlines() if line.strip()):
        if not any(candidate == line for candidate in remaining):
            sys.exit(f"Declaration page {number + 1 - article} lost or changed an original line")
PY

if [ "$signed" != "$dest" ]; then
  cp "$signed" "$dest"
fi
echo "Signed submission PDF: $dest"
echo "Intact digital signatures: $valid; content matches the validated build"
sha256sum "$dest"
