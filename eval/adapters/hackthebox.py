"""HackTheBox adapter — stub for retired web challenges with IDOR components."""
import os
import json


HTB_CHALLENGES = [
    {"id": "htb-01", "name": "BountyHunter", "notes": "XXE — mostly not IDOR", "skip": True},
    {"id": "htb-02", "name": "Horizontall", "notes": "API IDOR in Strapi CMS", "skip": False},
    {"id": "htb-03", "name": "ScriptKiddie", "notes": "Limited IDOR surface", "skip": True},
    {"id": "htb-04", "name": "Validation", "notes": "SQLi but similar param patterns", "skip": True},
    {"id": "htb-05", "name": "Ransom", "notes": "Auth bypass — IDOR adjacent", "skip": False},
]


def run_htb_challenge(challenge: dict, target_url: str) -> dict:
    """Run agent against a HackTheBox target. Requires VPN + manual setup."""
    if challenge.get("skip"):
        return {"id": challenge["id"], "skipped": True, "reason": "Low IDOR relevance"}

    api_key = os.environ.get("HTB_API_KEY", "")
    if not api_key:
        return {"id": challenge["id"], "skipped": True, "reason": "HTB_API_KEY not set"}

    import subprocess, tempfile
    users = [{"email": "htb_user", "password": "htb_pass", "label": "userA"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(users, f)
        users_file = f.name

    output_file = f"/tmp/htb_{challenge['id']}_findings.json"
    try:
        subprocess.run(
            ["python", "agent/main.py", "--target", target_url,
             "--users", users_file, "--output", output_file, "--max-steps", "30"],
            timeout=300,
        )
        findings = json.loads(open(output_file).read()) if os.path.exists(output_file) else []
        return {"id": challenge["id"], "findings": findings, "target_url": target_url}
    except Exception as e:
        return {"id": challenge["id"], "error": str(e)}
    finally:
        os.unlink(users_file)


def run_htb_suite() -> list[dict]:
    """NOTE: Requires active HackTheBox VPN + manually specified IPs."""
    print("[!] HackTheBox requires VPN and manual target setup. Returning stub.")
    return [{"id": c["id"], "name": c["name"], "status": "requires_manual_setup"}
            for c in HTB_CHALLENGES]
