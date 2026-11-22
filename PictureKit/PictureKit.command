#!/bin/zsh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "PictureKitの環境がありません。Terminalで次を実行してください:"
  echo "python3 -m venv '$SCRIPT_DIR/.venv'"
  echo "'$SCRIPT_DIR/.venv/bin/pip' install -r '$SCRIPT_DIR/requirements.txt'"
  exit 1
fi
exec "$PYTHON" "$SCRIPT_DIR/picturekit.py"
