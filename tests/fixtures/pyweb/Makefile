.PHONY: test lint run

test:
	pytest -q tests

lint:
	ruff check app tests

run:
	uvicorn app.main:app --reload
