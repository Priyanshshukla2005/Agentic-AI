#!/usr/bin/env bash
# Start Business Starter on Mac / Linux:   ./run.sh
# 1. creates a virtual environment (venv/) if missing   2. installs the requirements
# 3. copies .env.example to .env if missing             4. starts the server for this computer + the Wi-Fi
set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if [ ! -d venv ]; then
  echo "Creating virtual environment in venv/ ..."
  "$PYTHON" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "Installing requirements (first time can take a few minutes) ..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example - add your GROQ_API_KEY there (or set LLM_PROVIDER=mock)."
fi

PORT=${PORT:-8000}
LAN_IP=$( (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || echo "") | awk '{print $1}')
echo ""
echo "  On this computer : http://127.0.0.1:${PORT}"
if [ -n "$LAN_IP" ]; then
  echo "  On a phone (same Wi-Fi): http://${LAN_IP}:${PORT}"
fi
echo "  Press Ctrl+C to stop."
echo ""
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
