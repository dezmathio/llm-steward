# =============================================================================
# LLM Gateway Kit - Makefile
# =============================================================================
# Quick commands for operating the gateway.

.PHONY: help up down logs shell clean test seed team key cli

# Default target
help:
	@echo "LLM Gateway Kit - Available Commands"
	@echo ""
	@echo "  make up        - Start all services (gateway, database, dashboard)"
	@echo "  make down      - Stop all services"
	@echo "  make logs      - Follow logs from all services"
	@echo "  make shell     - Open a shell in the LiteLLM container"
	@echo "  make clean     - Stop services and remove volumes"
	@echo ""
	@echo "  make seed      - Generate demo traffic from fake teams"
	@echo "  make test      - Run all tests"
	@echo "  make eval      - Run eval test suite against the gateway"
	@echo ""
	@echo "  make team NAME=support BUDGET=50  - Create a new team"
	@echo "  make key TEAM=support USER=alice  - Create a new API key"
	@echo ""
	@echo "  make cli ARGS='team list'         - Run any CLI command"
	@echo ""
	@echo "Dashboard: http://localhost:8080"
	@echo "Gateway:   http://localhost:4000"

# -----------------------------------------------------------------------------
# Docker Compose Operations
# -----------------------------------------------------------------------------

up: .env
	@echo "Starting LLM Gateway..."
	docker compose up -d
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@echo "Pulling Ollama model (this may take a few minutes on first run)..."
	@docker compose exec -T ollama ollama pull qwen2.5:0.5b || true
	@echo ""
	@echo "✓ Gateway is ready!"
	@echo ""
	@echo "  Dashboard: http://localhost:8080"
	@echo "  Gateway:   http://localhost:4000"
	@echo "  Postgres:  localhost:5432"
	@echo ""
	@echo "Run 'make seed' to generate demo traffic."

down:
	docker compose down

logs:
	docker compose logs -f

logs-litellm:
	docker compose logs -f litellm

logs-dashboard:
	docker compose logs -f dashboard

shell:
	docker compose exec litellm /bin/bash

clean:
	docker compose down -v
	@echo "✓ All services stopped and volumes removed."

restart:
	docker compose restart

# Create .env from example if it doesn't exist
.env:
	@if [ ! -f .env ]; then \
		echo "Creating .env from .env.example..."; \
		cp .env.example .env; \
	fi

# -----------------------------------------------------------------------------
# Team and Key Management
# -----------------------------------------------------------------------------

team:
ifndef NAME
	@echo "Usage: make team NAME=<team-name> [BUDGET=100] [RPM=100] [MODELS=...] [PII=true]"
	@exit 1
endif
	@python3 cli/gateway_cli.py team create \
		--name $(NAME) \
		--budget $(or $(BUDGET),100) \
		--rpm $(or $(RPM),100) \
		$(if $(MODELS),--models $(MODELS)) \
		$(if $(PII),--pii-guardrail)

key:
ifndef TEAM
	@echo "Usage: make key TEAM=<team-name> [USER=<user-id>] [BUDGET=...]"
	@exit 1
endif
	@python3 cli/gateway_cli.py key create \
		--team $(TEAM) \
		$(if $(USER),--user $(USER)) \
		$(if $(BUDGET),--budget $(BUDGET))

# Run any CLI command
cli:
	@python3 cli/gateway_cli.py $(ARGS)

# -----------------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------------

test:
	@echo "Running tests..."
	pytest tests/ -v

test-integration:
	@echo "Running integration tests (requires running gateway)..."
	pytest tests/ -v -m integration

eval:
	@echo "Running eval suite..."
	pytest evals/ -v --eval-mode

# -----------------------------------------------------------------------------
# Demo and Development
# -----------------------------------------------------------------------------

seed:
	@echo "Generating demo traffic..."
	@python3 scripts/seed_traffic.py
	@echo ""
	@echo "✓ Demo traffic generated! Check the dashboard at http://localhost:8080"

dev-dashboard:
	@cd dashboard && uvicorn app:app --reload --port 8080

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

health:
	@curl -s http://localhost:4000/health | python3 -m json.tool

models:
	@python3 cli/gateway_cli.py models

stats:
	@python3 cli/gateway_cli.py stats

refresh-views:
	@docker compose exec postgres psql -U litellm -d litellm -c "SELECT refresh_usage_views();"

psql:
	@docker compose exec postgres psql -U litellm -d litellm

# Build dashboard image
build-dashboard:
	docker build -t llm-gateway-dashboard ./dashboard
