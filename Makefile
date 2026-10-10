PYTHON ?= python3
VENV ?= .venv
BIN ?= $(VENV)/bin

.PHONY: help setup run eval test clean

help:
	@echo "AI Procurement Request Copilot - Available commands:"
	@echo "  make setup   - Create virtual environment and install dependencies"
	@echo "  make run     - Start mock vendor-risk API and Streamlit UI"
	@echo "  make eval    - Run benchmark evaluation across all 30+ test cases"
	@echo "  make test    - Run pytest unit tests"
	@echo "  make clean   - Remove virtualenv and temporary files"

setup:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV) || python3.12 -m venv $(VENV) || python3.11 -m venv $(VENV); \
	fi
	@echo "Installing requirements..."
	@$(BIN)/pip install --upgrade pip
	@$(BIN)/pip install -r requirements.txt
	@$(BIN)/pip install pytest pytest-asyncio google-genai openai

run: setup
	@echo "Starting AI Procurement Copilot (Mock API + Streamlit UI)..."
	@PYTHONPATH=. $(BIN)/python run_local.py

eval: setup
	@echo "Running evaluation on benchmark test set..."
	@PYTHONPATH=. $(BIN)/python eval/run_eval.py

test: setup
	@echo "Running unit test suite..."
	@PYTHONPATH=. $(BIN)/pytest

clean:
	rm -rf $(VENV) __pycache__ */__pycache__ */*/__pycache__ .pytest_cache
