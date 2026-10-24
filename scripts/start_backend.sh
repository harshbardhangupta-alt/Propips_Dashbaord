#!/usr/bin/env bash
# Start the FastAPI backend on 127.0.0.1:8000 (macOS / Linux). PAPER TRADING ONLY.
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python run.py
