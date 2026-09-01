"""Vulhub CVE adapter — Docker-based CVE environments with IDOR components."""
import os
import json
import subprocess
from pathlib import Path


VULHUB_TARGETS = [
    {
        "id": "vulhub-01",
        "cve": "CVE-2018-3760",
        "product": "Sprockets (Rails)",
        "port": 3001,
        "notes": "Path traversal + info disclosure",
        "compose_path": "sprockets/CVE-2018-3760",
    },
    {
        "id": "vulhub-02",
        "cve": "CVE-2019-11248",
        "product": "Kubernetes debug endpoint",
        "port": 10255,
        "notes": "Unauthenticated API access — IDOR adjacent",
        "compose_path": "kubernetes/CVE-2019-11248",
    },
    {
        "id": "vulhub-03",
        "cve": "CVE-2021-21315",
        "product": "systeminformation IDOR",
        "port": 3002,
        "notes": "Command injection, but API IDOR pattern",
        "compose_path": "systeminformation/CVE-2021-21315",
    },
]

VULHUB_DIR = os.environ.get("VULHUB_DIR", os.path.expanduser("~/vulhub"))


def start_vulhub_env(target: dict) -> bool:
    compose_path = Path(VULHUB_DIR) / target["compose_path"]
    if not compose_path.exists():
        print(f"[!] Vulhub path not found: {compose_path}")
        return False
    result = subprocess.run(
        ["docker-compose", "up", "-d"],
        cwd=str(compose_path),
        capture_output=True,
    )
    return result.returncode == 0


def stop_vulhub_env(target: dict):
    compose_path = Path(VULHUB_DIR) / target["compose_path"]
    subprocess.run(["docker-compose", "down", "-v"], cwd=str(compose_path), capture_output=True)


def run_vulhub_target(target: dict) -> dict:
    base_url = f"http://localhost:{target['port']}"
    users = [{"email": "admin", "password": "admin", "label": "userA"}]

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(users, f)
        users_file = f.name

    output_file = f"/tmp/vulhub_{target['id']}_findings.json"

    if not start_vulhub_env(target):
        os.unlink(users_file)
        return {"id": target["id"], "error": "Could not start vulhub env", "cve": target["cve"]}

    import time
    time.sleep(10)  # Wait for service

    try:
        subprocess.run(
            ["python", "agent/main.py", "--target", base_url,
             "--users", users_file, "--output", output_file, "--max-steps", "20"],
            timeout=180,
        )
        findings = json.loads(open(output_file).read()) if os.path.exists(output_file) else []
        return {"id": target["id"], "cve": target["cve"], "findings": findings}
    except Exception as e:
        return {"id": target["id"], "cve": target["cve"], "error": str(e)}
    finally:
        os.unlink(users_file)
        stop_vulhub_env(target)


def run_vulhub_suite() -> list[dict]:
    print("[!] Vulhub requires manual setup. Returning stub results.")
    return [{"id": t["id"], "cve": t["cve"], "status": "requires_manual_setup"}
            for t in VULHUB_TARGETS]
