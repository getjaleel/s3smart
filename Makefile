# ==========================================================
# s3smart Makefile
# Fast, Reliable AWS S3 Transfers & Sync Utility
# ==========================================================

PACKAGE = s3smart
PYTHON = python
PIP = pip
SRC = $(PACKAGE)
VENV ?= .venv

# ----------------------------------------------------------
# Setup & Install
# ----------------------------------------------------------

.PHONY: install
install:
	@echo "🚀 Installing $(PACKAGE) in editable mode..."
	$(PIP) install -e .

.PHONY: reinstall
reinstall:
	@echo "♻️  Reinstalling package..."
	$(PIP) uninstall -y $(PACKAGE) || true
	$(PIP) install -e .

.PHONY: deps
deps:
	@echo "📦 Installing dependencies..."
	$(PIP) install -r requirements.txt || true
	$(PIP) install boto3 tqdm colorama flake8

# ----------------------------------------------------------
# Lint & Check
# ----------------------------------------------------------

.PHONY: lint
lint:
	@echo "🧹 Running flake8 linting..."
	flake8 $(SRC) --max-line-length=88 --ignore=E203,W503

.PHONY: fmt
fmt:
	@echo "✨ Formatting with black..."
	black $(SRC)

# ----------------------------------------------------------
# Run Commands
# ----------------------------------------------------------

.PHONY: browse
browse:
	@echo "🔍 Launching S3 browser..."
	$(PYTHON) -m $(PACKAGE).cli browse

.PHONY: version
version:
	@$(PYTHON) -m $(PACKAGE).cli --version

# ----------------------------------------------------------
# Clean Up
# ----------------------------------------------------------

.PHONY: clean
clean:
	@echo "🧼 Cleaning build artifacts..."
	rm -rf build dist *.egg-info __pycache__ */__pycache__

.PHONY: reset
reset:
	@echo "🔥 Full reset..."
	rm -rf $(VENV) build dist *.egg-info __pycache__ */__pycache__
	find . -type f -name "*.pyc" -delete
