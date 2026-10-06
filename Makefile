.PHONY: up full down logs ps verify measure dashboards chaos-cpu chaos-latency chaos-errors kill-inventory restore clean

up:            ## start the core stack
	@[ -f .env ] || cp .env.example .env
	docker compose up -d --build
full:          ## core stack + cAdvisor
	docker compose --profile full up -d --build
down:
	docker compose --profile full down
logs:
	docker compose logs -f --tail=50
ps:
	docker compose ps
verify:
	./scripts/verify.sh
measure:
	./scripts/measure.sh
dashboards:    ## regenerate grafana/dashboards/*.json
	python3 scripts/gen_dashboards.py
chaos-cpu:
	./scripts/chaos-cpu.sh
chaos-latency:
	./scripts/chaos-latency.sh
chaos-errors:
	./scripts/chaos-errors.sh
kill-inventory:
	./scripts/chaos-kill-inventory.sh
restore:
	./scripts/chaos-restore.sh
clean:         ## stop and delete all data volumes
	docker compose --profile full down -v
