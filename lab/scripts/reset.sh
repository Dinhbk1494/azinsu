#!/bin/bash
set -e

echo "[*] Resetting IDOR lab..."
docker-compose -f "$(dirname "$0")/../docker-compose.yml" down -v
docker-compose -f "$(dirname "$0")/../docker-compose.yml" up -d
echo "[*] Waiting for services to start..."
sleep 15
echo "[*] Seeding database..."
docker-compose -f "$(dirname "$0")/../docker-compose.yml" exec custom-idor-lab python data/seed.py
echo "[OK] Lab reset complete."
echo "  Juice Shop:       http://localhost:3000"
echo "  VAmPI:            http://localhost:5000"
echo "  Custom IDOR Lab:  http://localhost:8080"
