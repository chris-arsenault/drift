.PHONY: lint lint-fix format format-check test \
       lint-extractor lint-fix-extractor format-extractor format-check-extractor \
       lint-pipeline lint-fix-pipeline format-pipeline format-check-pipeline \
       test-pipeline

lint: lint-extractor lint-pipeline
lint-fix: lint-fix-extractor lint-fix-pipeline
format: format-extractor format-pipeline
format-check: format-check-extractor format-check-pipeline

lint-extractor:
	cd extractor && npx eslint .

lint-fix-extractor:
	cd extractor && npx eslint . --fix

format-extractor:
	cd extractor && npx prettier --write .

format-check-extractor:
	cd extractor && npx prettier --check .

lint-pipeline:
	cd pipeline && python3 -m ruff check src/

lint-fix-pipeline:
	cd pipeline && python3 -m ruff check --fix src/

format-pipeline:
	cd pipeline && python3 -m ruff format src/

format-check-pipeline:
	cd pipeline && python3 -m ruff format --check src/

test: test-pipeline

test-pipeline:
	cd pipeline && python3 -m pytest tests/ -v
