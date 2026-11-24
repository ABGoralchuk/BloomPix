#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_EXE="./venv/bin/python"

if [ ! -x "$PYTHON_EXE" ]; then
    echo "[BloomPix] Creating virtual environment in ./venv..."
    python3 -m venv venv
    "$PYTHON_EXE" -m pip install --upgrade pip
    "$PYTHON_EXE" -m pip install -r requirements.txt
elif ! "$PYTHON_EXE" -c "import streamlit" >/dev/null 2>&1; then
    echo "[BloomPix] Installing dependencies from requirements.txt..."
    "$PYTHON_EXE" -m pip install -r requirements.txt
fi

echo "[BloomPix] Starting Streamlit application..."
exec "$PYTHON_EXE" -m streamlit run app.py --server.headless false
