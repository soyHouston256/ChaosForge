#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
DEST="$ROOT/vendor/microservices-demo"
REF="${BOUTIQUE_REF:-v0}"
if [[ -d "$DEST/.git" ]]; then echo "Existe $DEST. Commit:"; git -C "$DEST" rev-parse HEAD; exit 0; fi
mkdir -p "$ROOT/vendor"
git clone --depth 1 --branch "$REF" https://github.com/GoogleCloudPlatform/microservices-demo.git "$DEST"
echo 'Commit desplegable:'; git -C "$DEST" rev-parse HEAD
