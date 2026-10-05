#!/bin/bash
set -euo pipefail
TOOL_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x "$TOOL_DIR/.venv/bin/python" ]; then
  python3 -m venv "$TOOL_DIR/.venv"
fi
if [ ! -x "$TOOL_DIR/.venv/bin/google-maps-reviews" ]; then
  echo "初回の準備：口コミ収集ツールをインストールします。"
  "$TOOL_DIR/.venv/bin/python" -m pip install --editable "$TOOL_DIR"
fi
exec "$TOOL_DIR/.venv/bin/google-maps-reviews" "$@"
