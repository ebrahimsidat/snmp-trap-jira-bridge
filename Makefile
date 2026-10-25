install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

typecheck:
	python -m mypy

test:
	python -m pytest

check: lint typecheck test

format:
	ruff format .
	ruff check --fix .

.PHONY: install lint typecheck test check format
