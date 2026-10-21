#!/usr/bin/env bash
# Fails if files about to be published contain private Foundry details.
# Prints only file:line and the rule name, never the matched value.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

rules=(
  "foundry-host|[A-Za-z0-9-]+\.palantirfoundry\.(com|net)"
  "resource-id|ri\.[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9-]+\.[0-9a-f]{8}-[0-9a-f]{4}"
  "url-credential|https?://[^/@[:space:]]+@"
  "bearer-token|[Bb]earer[[:space:]]+[A-Za-z0-9._-]{20,}"
  "jwt|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
  "email|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

self="scripts/check-public-safe.sh"

# Optional local blocklist of business words (git-ignored, one per line).
words_file=".public-safe-words"
if [[ -f "$words_file" ]]; then
  while IFS= read -r word; do
    [[ -z "$word" || "$word" == \#* ]] && continue
    rules+=("business-word|$(printf '%s' "$word" | sed 's/[][\\.^$*+?(){}|/]/\\&/g')")
  done < "$words_file"
fi
found=0

while IFS= read -r -d '' file; do
  [[ "$file" == "$self" ]] && continue
  for rule in "${rules[@]}"; do
    name="${rule%%|*}"
    pattern="${rule#*|}"
    while IFS=: read -r line _; do
      echo "BLOCKED $file:$line ($name)"
      found=1
    done < <(grep -nIE "$pattern" "$file" 2>/dev/null || true)
  done
done < <(git ls-files -z --cached --others --exclude-standard)

if [[ $found -ne 0 ]]; then
  echo "check-public-safe: private details found; remove them before committing." >&2
  exit 1
fi
echo "check-public-safe: OK"
