COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up up-web up-api dev dev-db dev-api dev-web down build logs ps docs docs-build

# ── Production-like (Docker) ───────────────────────────────────────────────
up: ## Rebuild and restart web + api (db untouched)
	$(COMPOSE) up --build web api -d
	@echo "App running at http://localhost:3000"

up-web: ## Rebuild and restart web only
	$(COMPOSE) up --build web -d
	@echo "Web running at http://localhost:3000"

up-api: ## Rebuild and restart api only
	$(COMPOSE) up --build api -d
	@echo "API running at http://localhost:8000"

# ── Development (hot reload) ───────────────────────────────────────────────
dev: ## Start DB in Docker + API and web with hot reload (single terminal)
	$(COMPOSE) up db -d
	@echo "Waiting for DB..."
	@$(COMPOSE) exec -T db sh -c 'until pg_isready -U postgres -d configent; do sleep 1; done'
	npx --yes concurrently \
	  --names "api,web" \
	  --prefix-colors "cyan,green" \
	  "cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" \
	  "cd apps/web && npm run dev"

dev-db: ## Start only the database (background)
	$(COMPOSE) up db -d
	@echo "DB ready at localhost:5432"

dev-api: ## Run API locally with auto-reload
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-web: ## Run web locally with hot reload
	cd apps/web && npm run dev

# ── Shared ─────────────────────────────────────────────────────────────────
down: ## Stop and remove all containers (data volume preserved)
	$(COMPOSE) down

build: ## Rebuild all images without starting
	$(COMPOSE) build

logs: ## Tail logs from all services (Ctrl-C to stop)
	$(COMPOSE) logs -f

ps: ## Show running service status
	$(COMPOSE) ps

docs: ## Docs site dev server → http://localhost:4321/configent
	cd apps/docs && npm run dev

docs-build: ## Build docs for GitHub Pages → apps/docs/dist/
	cd apps/docs && npm run build
