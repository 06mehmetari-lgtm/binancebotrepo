.PHONY: up down build logs ps clean migrate-risk-limits

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

# system_risk_limits tablosu (mevcut Postgres; yeni kurulumda init.sql zaten oluşturur)
migrate-risk-limits:
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-prometheus} -d prometheus_trading -f /migrations/002_system_risk_limits.sql
