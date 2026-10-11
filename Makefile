.PHONY: install dev test lint format migrate docker-up docker-down \
        engine-build engine-test backup restore

install:
	cd server && pip install -r requirements.txt
	cd web && npm install

# Development stack: Vite hot reload, ports on 127.0.0.1, placeholder secrets.
# The proxy is on http://localhost:8080 (see .env.dev).
dev:
	docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up --build

test:
	cd server && pytest
	$(MAKE) client-test
	$(MAKE) engine-test

# The sync client's tests run the real server application in-process (they
# import ../server), so they need the server's dependencies installed too.
client-test:
	cd client && pytest

lint:
	cd server && ruff check app tests
	cd client && ruff check .
	cd web && npm run lint

format:
	cd server && ruff format app tests
	cd web && npm run format

migrate:
	cd server && bash scripts/migrate.sh

# Run migrations inside the running backend container (use this after
# `make docker-up` / `docker compose up` on a fresh database).
docker-migrate:
	docker compose exec backend bash scripts/migrate.sh

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

engine-build:
	cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
	cmake --build engine/build --parallel

engine-test: engine-build
	ctest --test-dir engine/build --output-on-failure

backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh