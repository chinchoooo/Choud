.PHONY: install dev test lint format migrate docker-up docker-down \
        engine-build engine-test backup restore

install:
	cd server && pip install -r requirements.txt
	cd web && npm install

dev:
	docker compose up

test:
	cd server && pytest
	$(MAKE) engine-test

lint:
	cd server && ruff check app tests
	cd web && npm run lint

format:
	cd server && ruff format app tests
	cd web && npm run format

migrate:
	cd server && alembic upgrade head

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
