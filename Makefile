COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down build logs ps docs docs-build

up: ## Start all services (build if needed)
	$(COMPOSE) up --build -d
	@echo "App running at http://localhost:3000"

down: ## Stop and remove containers
	$(COMPOSE) down

build: ## Rebuild images without starting
	$(COMPOSE) build

logs: ## Tail logs from all services (Ctrl-C to stop)
	$(COMPOSE) logs -f

ps: ## Show running service status
	$(COMPOSE) ps

docs: ## Docs site dev server → http://localhost:4321/configent
	cd apps/docs && npm run dev

docs-build: ## Build docs for GitHub Pages → apps/docs/dist/
	cd apps/docs && npm run build
