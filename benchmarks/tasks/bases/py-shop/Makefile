PYTHON ?= python3

.PHONY: test lint clean

test:
	$(PYTHON) -m unittest discover -s tests -t . -p "test_*.py"

lint:
	$(PYTHON) -m compileall -q shop tests

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
