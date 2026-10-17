#!/usr/bin/env bash
set -euo pipefail
for cmd in git terraform gcloud kubectl python3; do
 if command -v "$cmd" >/dev/null; then echo "OK: $cmd"; else echo "FALTA: $cmd"; fi
done
