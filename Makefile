format:
	@echo "Running Ruff format..." && ruff format . --config pyproject.toml --exclude main.py,handlers/payments
	@echo "Running Ruff..." && ruff check . --config pyproject.toml --exclude main.py,handlers/payments --fix

lint:
	@echo "Running Ruff checks..." && ruff check . --config pyproject.toml --exclude main.py,handlers/payments

format-payments:
	@echo "Running Ruff format ONLY on handlers/payments..." && ruff format handlers/payments --config pyproject.toml
	@echo "Running Ruff check ONLY on handlers/payments..." && ruff check handlers/payments --config pyproject.toml --fix

test:
	@echo "Running unit tests..." && cd /tmp && PYTHONPATH="$(CURDIR)" "$(CURDIR)/venv/bin/python" -m unittest discover -s "$(CURDIR)/tests" -q

test-sudo:
	@echo "Running unit tests with sudo..." && cd /tmp && sudo env PYTHONPATH="$(CURDIR)" "$(CURDIR)/venv/bin/python" -m unittest discover -s "$(CURDIR)/tests" -q

smoke:
	@echo "Running smoke checks..." && bash "$(CURDIR)/tests/smoke_runner.sh"
