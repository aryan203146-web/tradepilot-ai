#!/bin/bash
# TradePilot AI — Start Script
# ==============================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
BACKEND_DIR="$PROJECT_DIR/backend"

echo ""
echo "  ⚡ TradePilot AI — Intraday F&O Signal System"
echo "  ================================================"
echo "  Mode: PAPER TRADING (Real money: DISABLED)"
echo ""

# Create virtual environment if not exists
if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r "$PROJECT_DIR/requirements.txt"

echo ""
echo "🚀 Starting TradePilot AI server..."
echo "   Dashboard: http://localhost:8000"
echo "   API Docs:  http://localhost:8000/api/docs"
echo "   Press Ctrl+C to stop"
echo ""

# Start server
cd "$BACKEND_DIR"
python main.py
