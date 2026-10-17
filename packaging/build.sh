#!/usr/bin/env bash
# Local Linux build: ./packaging/build.sh  ->  dist/skibasar
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --group build pyinstaller --noconfirm --clean packaging/skibasar.spec
echo "Fertig: dist/skibasar"
