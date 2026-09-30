.PHONY: help install dev test lint type docs docs-check check build clean self-bom

help:
	@echo "aibom — common tasks"
	@echo "  make install     install the package"
	@echo "  make dev         editable install with dev extras"
	@echo "  make test        run the test suite (excluding slow)"
	@echo "  make lint        ruff check"
	@echo "  make type        mypy"
	@echo "  make docs        regenerate docs/risk-rules.md from the rulebook YAML"
	@echo "  make docs-check  fail if docs/risk-rules.md is stale"
	@echo "  make check       lint + type + docs-check + test"
	@echo "  make build       build sdist and wheel"
	@echo "  make self-bom    generate aibom's own AI BOM"

install:
	python -m pip install .

dev:
	python -m pip install -e ".[dev,xml,pdf]"
	pre-commit install --hook-type pre-commit

test:
	pytest -m "not slow"

lint:
	ruff check src tests

type:
	mypy

docs:
	python -m aibom.risk.docs

docs-check:
	python -m aibom.risk.docs --check

check: lint type docs-check test

build:
	python -m build

self-bom:
	aibom generate . -o aibom.cdx.json --markdown AIBOM.md --refresh
	aibom validate aibom.cdx.json

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
