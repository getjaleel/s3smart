PYTHON = python3
VENV = .venv
SRC = s3smart.py

.PHONY: all install lint run clean

all: install lint

install:
	@echo "Creating virtual environment..."
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@. $(VENV)/bin/activate; pip install --upgrade pip
	@. $(VENV)/bin/activate; pip install boto3 tqdm flake8
	@echo "Checking for s3smart.json..."
	@[ -f s3smart.json ] || echo '{ "browse_part_size_mb": 128, "default_part_size_mb": 256, "default_workers": 16 }' > s3smart.json
	@echo "Default s3smart.json ready."

lint:
	@. $(VENV)/bin/activate; flake8 $(SRC)

run:
	@. $(VENV)/bin/activate; $(PYTHON) $(SRC) browse

clean:
	rm -rf $(VENV) __pycache__ *.egg-info build dist
