#!/bin/zsh
set -e
APP_DIR="$(cd "$(dirname "$0")/app" && pwd)"
APP_PY="$APP_DIR/.venv/bin/python"
if [[ ! -x "$APP_PY" ]]; then
  python3 -m venv "$APP_DIR/.venv"
  "$APP_PY" -m pip install -r "$APP_DIR/requirements.txt"
fi
cd "$APP_DIR"
if curl -fsS http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then
  open http://127.0.0.1:8501
  exit 0
fi
open http://127.0.0.1:8501
exec "$APP_PY" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
