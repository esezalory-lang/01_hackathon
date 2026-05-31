#!/usr/bin/env bash
#
# run_demo.sh — launch the full Infineon demo from 01_hackathon:
#   1. the FastAPI agent backend (this repo) on :8000
#   2. the Lovable UI (sibling ../lovable_layer) on :8080, proxying /agent -> :8000
#
# A fresh clone of THIS repo alone can launch the UI: if the Lovable UI isn't
# found locally, it's cloned automatically from LOVABLE_REPO.
#
# Usage:
#   ./run_demo.sh                # mock backend (fast, no keys/network) + UI
#   USE_MOCK=0 ./run_demo.sh     # live Sybilion backend (needs SYBILION_API_KEY) + UI
#   LOVABLE_DIR=/path/to/ui ./run_demo.sh   # use a UI checkout in a custom location
#
# Ctrl-C stops both. Open http://localhost:8080 once it's up.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USE_MOCK="${USE_MOCK:-1}"
PORT_API="${PORT_API:-8000}"
LOVABLE_REPO="${LOVABLE_REPO:-https://github.com/esezalory-lang/infineon-chip-compass.git}"

command -v npm >/dev/null  || { echo "❌ npm/Node.js not found — install Node 18+ then re-run."; exit 1; }
command -v git >/dev/null  || { echo "❌ git not found — needed to fetch the UI."; exit 1; }

# --- locate (or fetch) the Lovable UI ---
# Priority: explicit LOVABLE_DIR > sibling ../lovable_layer (dev layout) >
#           ./lovable_layer (already cloned here) > clone it now.
if [ -n "${LOVABLE_DIR:-}" ]; then
  UI_DIR="$LOVABLE_DIR"
elif [ -d "$HERE/../lovable_layer/src" ]; then
  UI_DIR="$HERE/../lovable_layer"
elif [ -d "$HERE/lovable_layer/src" ]; then
  UI_DIR="$HERE/lovable_layer"
else
  UI_DIR="$HERE/lovable_layer"
  echo "▶ Lovable UI not found locally — cloning $LOVABLE_REPO"
  git clone --depth 1 "$LOVABLE_REPO" "$UI_DIR"
fi

if [ ! -d "$UI_DIR/src" ]; then
  echo "❌ '$UI_DIR' doesn't look like the Lovable UI (no src/)."
  echo "   Set LOVABLE_DIR=/path/to/lovable_layer (or LOVABLE_REPO=<git url>) and re-run."
  exit 1
fi

# --- backend deps (venv) ---
if [ ! -x "$HERE/.venv/bin/uvicorn" ]; then
  echo "▶ Creating .venv and installing backend deps…"
  python3 -m venv "$HERE/.venv"
  "$HERE/.venv/bin/pip" install -q --upgrade pip
  "$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
fi

# --- start backend (background); stop it when this script exits ---
echo "▶ Starting agent backend on http://localhost:$PORT_API  (USE_MOCK=$USE_MOCK)"
( cd "$HERE" && USE_MOCK="$USE_MOCK" "$HERE/.venv/bin/uvicorn" app:app --port "$PORT_API" ) &
API_PID=$!
trap 'echo; echo "▶ Stopping backend (pid $API_PID)…"; kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

# --- frontend deps ---
if [ ! -d "$UI_DIR/node_modules" ]; then
  echo "▶ Installing UI deps (npm install)… (first run only)"
  ( cd "$UI_DIR" && npm install )
fi

# --- start UI (foreground); the Vite proxy forwards /agent -> :$PORT_API ---
echo "▶ Starting Lovable UI → http://localhost:8080   (proxies /agent → :$PORT_API)"
echo "  (Ctrl-C to stop both.)"
cd "$UI_DIR" && npm run dev
