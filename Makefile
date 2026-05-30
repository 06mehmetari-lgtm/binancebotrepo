.PHONY: up down build logs ps clean

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

clean:
	docker compose down -v --remove-orphans

infra:
	docker compose up -d postgres timescale redis zookeeper kafka qdrant grafana prometheus_metrics

restart-%:
	docker compose restart $*
