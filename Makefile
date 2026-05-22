.PHONY: lint format typecheck test check install install-hooks lock

.venv:
	python3.12 -m venv .venv

lock: .venv
	.venv/bin/python scripts/lock_deps.py

install: .venv
	.venv/bin/pip install -r requirements.txt

install-hooks:
	cp hooks/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "Git hook installed."

lint:
	python -m flake8 src/

format:
	python -m isort src/
	python -m black src/

typecheck:
	python -m mypy src/

test:
	python -m pytest

check: format lint typecheck test
