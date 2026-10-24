#!/usr/bin/env bash
# Start the Vite dev server on 127.0.0.1:5173 (proxies /api to the backend).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install
exec npm run dev
