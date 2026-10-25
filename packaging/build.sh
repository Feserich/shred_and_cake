#!/usr/bin/env bash
# Local Linux build: ./packaging/build.sh  ->  dist/skibasar
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --group build pyinstaller --noconfirm --clean packaging/skibasar.spec
uv run --group build python packaging/build_docs.py
echo "Fertig: dist/skibasar"
