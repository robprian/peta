.PHONY: help up down logs migrate seed demo admin osm test test-integration lint fmt

help:
	@echo "make up       - start PostGIS + API"
	@echo "make migrate  - apply SQL migrations"
	@echo "make admin    - import batas wilayah BPS/Kemendagri"
	@echo "make osm      - import OSM (osmium + osm2pgsql)"
	@echo "make demo     - load small Bandung demo dataset"
	@echo "make test     - run backend tests (integration skipped without PETA_TEST_DATABASE_URL)"
	@echo "make test-integration - run PostGIS integration tests"
	@echo "make lint     - run ruff on backend and ETL"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api db

migrate:
	psql "$${DATABASE_URL:-postgresql://peta:peta_secret@localhost:5432/peta}" \
	  -v ON_ERROR_STOP=1 -f migrations/001_schema.sql \
	  -f migrations/002_indexes.sql -f migrations/003_functions.sql

admin:
	python3 etl/import_admin.py --data-dir data --database-url "$${DATABASE_URL:-postgresql://peta:peta_secret@localhost:5432/peta}"

osm:
	bash etl/run_osm_import.sh

demo:
	python3 etl/seed_demo.py --database-url "$${DATABASE_URL:-postgresql://peta:peta_secret@localhost:5432/peta}"

test:
	cd backend && pytest -q

test-integration:
	cd backend && PETA_TEST_DATABASE_URL="$${PETA_TEST_DATABASE_URL:-$${DATABASE_URL:-postgresql://peta:peta_secret@localhost:5432/peta}}" pytest -q -m integration

lint:
	ruff check backend/app etl

fmt:
	ruff check --fix backend etl || true
