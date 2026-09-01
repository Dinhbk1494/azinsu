"""Bug bounty adapter — real-world testing with strict safety controls."""
import os
import json
import subprocess
from pathlib import Path


# SAFETY: Only proceed if all conditions met
def check_safety_checklist(program: dict) -> tuple[bool, list[str]]:
    issues = []
    if not program.get("automation_allowed"):
        issues.append("Program does not explicitly allow automation")
    if not program.get("scope"):
        issues.append("No scope defined")
    if not program.get("rate_limit_rps"):
        issues.append("Rate limit not specified")
    if not program.get("human_review_required") is True:
        issues.append("Human review flag not set to True")
    return len(issues) == 0, issues


def run_bug_bounty_target(program: dict, target_url: str, users: list[dict]) -> dict:
    """
    Run agent against bug bounty target.
    REQUIRES all safety checks to pass.
    DOES NOT submit findings — human review required.
    """
    ok, issues = check_safety_checklist(program)
    if not ok:
        return {
            "error": "Safety checklist failed",
            "issues": issues,
            "findings": [],
        }

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(users, f)
        users_file = f.name

    output_file = f"/tmp/bb_{program.get('name', 'target')}_findings.json"

    # Enforce rate limit from program config
    rate_limit = min(program.get("rate_limit_rps", 0.5), 1.0)
    scope_flags = ["--scope", target_url]

    try:
        result = subprocess.run(
            ["python", "agent/main.py",
             "--target", target_url,
             "--users", users_file,
             "--output", output_file,
             "--max-steps", "40",
             *scope_flags],
            env={**os.environ, "RATE_LIMIT": str(rate_limit)},
            timeout=3600,
            capture_output=True,
            text=True,
        )

        findings = []
        if Path(output_file).exists():
            with open(output_file) as f:
                findings = json.load(f)

        return {
            "program": program.get("name"),
            "target": target_url,
            "findings_count": len(findings),
            "findings": findings,
            "human_review_required": True,
            "DO_NOT_SUBMIT": True,
        }
    except Exception as e:
        return {"error": str(e), "findings": []}
    finally:
        os.unlink(users_file)
