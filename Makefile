.PHONY: lab-up lab-down lab-reset verify-truth agent-run eval eval-custom eval-portswigger report senior-baseline install test

install:
	pip install -e .
	playwright install chromium

lab-up:
	docker-compose -f lab/docker-compose.yml up -d
	sleep 10
	python lab/custom-idor-lab/data/seed.py
	@echo "Lab is up. Juice-shop: http://localhost:3000 | VAmPI: http://localhost:5000 | Custom: http://localhost:8080"

lab-down:
	docker-compose -f lab/docker-compose.yml down -v

lab-reset:
	bash lab/scripts/reset.sh

verify-truth:
	python lab/scripts/verify_truth.py

agent-run:
	@if [ -z "$(TARGET)" ]; then echo "Usage: make agent-run TARGET=http://localhost:8080 USERS=lab/users.json"; exit 1; fi
	python agent/main.py --target $(TARGET) --users $(USERS)

eval:
	python eval/harness.py --suite all

eval-custom:
	python eval/harness.py --suite custom

eval-portswigger:
	python eval/harness.py --suite portswigger

report:
	python eval/harness.py --generate-report

senior-baseline:
	python eval/baselines/run_senior_test.py

test:
	pytest tests/ -v

clean-runs:
	rm -rf runs/run_*
