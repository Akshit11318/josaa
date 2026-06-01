.PHONY: up down migrate crawl predict stats shell logs

up:            ## start postgres + app containers
	docker compose up -d --build

down:          ## stop containers (keeps the pgdata volume)
	docker compose down

migrate:       ## apply DB migrations
	docker compose exec app alembic upgrade head

crawl:         ## crawl ORCR (2025,2024,2023) + current seat matrix
	docker compose exec app python -m josaa.cli crawl

stats:         ## show what's in the DB
	docker compose exec app python -m josaa.cli stats

export:        ## export Postgres -> docs/data/josaa.sqlite (run after crawl)
	docker compose exec app python /app/export_sqlite.py
	docker compose exec app chown -R 1000:1000 docs

web:           ## the static site (docs/) is served by the app container
	@echo "Open http://localhost:8000  — same files GitHub Pages will serve"

# usage: make predict ARGS="--exam jee_adv --rank 5000 --gender female --ai"
predict:
	docker compose exec app python -m josaa.cli predict $(ARGS)

shell:         ## open a shell in the app container
	docker compose exec app bash

logs:
	docker compose logs -f
