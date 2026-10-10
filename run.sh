#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== Starting AI Procurement Request Copilot ==="

# Check virtualenv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment .venv..."
    python3.12 -m venv .venv 2>/dev/null || python3.11 -m venv .venv 2>/dev/null || python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install pytest pytest-asyncio google-genai openai
fi

export PYTHONPATH="."
export MOCK_LLM="${MOCK_LLM:-1}"

exec .venv/bin/python run_local.py
