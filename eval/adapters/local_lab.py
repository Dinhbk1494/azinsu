"""Adapter for running agent against local Docker lab targets."""
import json
import subprocess
import os
from pathlib import Path


GROUND_TRUTH_DIR = Path(__file__).parent.parent.parent / "lab" / "ground_truth"


def run_agent_on_target(target_name: str, base_url: str, ground_truth: dict) -> dict:
    """Run the IDOR hunter agent on a local lab target."""
    users = ground_truth.get("users", [])

    # Write users to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(users, f)
        users_file = f.name

    output_file = f"/tmp/findings_{target_name}.json"

    try:
        result = subprocess.run(
            ["python", "agent/main.py",
             "--target", base_url,
             "--users", users_file,
             "--output", output_file],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        if result.returncode != 0 and not Path(output_file).exists():
            return {"error": result.stderr, "findings": []}

        if Path(output_file).exists():
            with open(output_file) as f:
                findings = json.load(f)
            return {"findings": findings, "stdout": result.stdout}

        return {"findings": [], "stderr": result.stderr}
    finally:
        os.unlink(users_file)
        if Path(output_file).exists():
            os.unlink(output_file)


def load_ground_truth(name: str) -> dict:
    gt_file = GROUND_TRUTH_DIR / f"{name}.json"
    if not gt_file.exists():
        raise FileNotFoundError(f"Ground truth not found: {gt_file}")
    return json.loads(gt_file.read_text())
