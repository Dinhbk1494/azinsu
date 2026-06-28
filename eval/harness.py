#!/usr/bin/env python3
"""Main evaluation harness — runs agent against all suites and generates report."""
import json
import os
import sys
import subprocess
import tempfile
import click
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.scorer import score_run, score_by_difficulty
from eval.maturity_calculator import calculate_maturity, format_report
from eval.failure_analyzer import analyze_failures, format_failure_report

GROUND_TRUTH_DIR = Path(__file__).parent.parent / "lab" / "ground_truth"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def run_agent(target_url: str, users: list, max_steps: int = 50) -> list[dict]:
    """Run the IDOR hunter agent and return findings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(users, f)
        users_file = f.name

    output_file = f"/tmp/harness_findings_{os.getpid()}.json"

    try:
        result = subprocess.run(
            ["python", "agent/main.py",
             "--target", target_url,
             "--users", users_file,
             "--output", output_file,
             "--max-steps", str(max_steps)],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).parent.parent),
        )
        print(result.stdout[-2000:] if result.stdout else "")
        if result.stderr:
            print(f"[stderr] {result.stderr[-500:]}", file=sys.stderr)

        if Path(output_file).exists():
            with open(output_file) as f:
                return json.load(f)
        return []
    except subprocess.TimeoutExpired:
        print("[!] Agent timed out")
        return []
    except Exception as e:
        print(f"[!] Agent error: {e}")
        return []
    finally:
        os.unlink(users_file)
        if Path(output_file).exists():
            os.unlink(output_file)


def run_custom_suite() -> dict:
    """Run against custom IDOR lab."""
    gt = json.loads((GROUND_TRUTH_DIR / "custom-idor-lab.json").read_text())
    base_url = gt["base_url"]
    users = gt["users"]

    print(f"\n[*] Running CUSTOM IDOR LAB suite ({base_url})")
    print(f"    {len(gt['idors'])} IDORs to find...")

    findings = run_agent(base_url, users)
    score = score_run(findings, gt)
    by_diff = score_by_difficulty(findings, gt)

    print(f"    Found: {len(score.true_positives)}/{gt['idors'].__len__()}")
    print(f"    Precision: {score.precision*100:.1f}% | Recall: {score.recall*100:.1f}%")

    result = score.to_dict()
    result["suite"] = "custom-idor-lab"
    result["difficulty_breakdown"] = by_diff
    result["findings"] = findings
    return result


def run_portswigger_suite() -> dict:
    """Run against PortSwigger Web Academy labs."""
    email = os.environ.get("PORTSWIGGER_EMAIL", "")
    password = os.environ.get("PORTSWIGGER_PASSWORD", "")

    if not email or not password:
        print("[!] Skipping PortSwigger — PORTSWIGGER_EMAIL/PASSWORD not set")
        return {"suite": "portswigger", "skipped": True, "total_ground_truth": 13,
                "true_positives": [], "false_positives": [], "false_negatives": list(range(13)),
                "precision": 0, "recall": 0, "f1": 0}

    from eval.adapters.portswigger import run_portswigger_suite, PORTSWIGGER_LABS
    print(f"\n[*] Running PORTSWIGGER suite ({len(PORTSWIGGER_LABS)} labs)")
    results = run_portswigger_suite(email, password)
    solved = [r for r in results if r.get("solved")]
    not_solved = [r for r in results if not r.get("solved") and not r.get("skipped")]

    return {
        "suite": "portswigger",
        "target": "portswigger",
        "total_ground_truth": len(PORTSWIGGER_LABS),
        "true_positives": [r["lab_id"] for r in solved],
        "false_positives": [],
        "false_negatives": [r["lab_id"] for r in not_solved],
        "precision": 1.0 if solved else 0.0,
        "recall": len(solved) / len(PORTSWIGGER_LABS) if PORTSWIGGER_LABS else 0.0,
        "f1": 0.0,
    }


def generate_report(all_results: list[dict], run_date: str) -> str:
    """Generate Markdown maturity report."""
    senior_file = Path(__file__).parent / "baselines" / "senior_baseline.json"
    senior_data = None
    if senior_file.exists():
        senior_raw = json.loads(senior_file.read_text())
        senior_data = senior_raw.get("summary")

    report = calculate_maturity(all_results, senior_data)
    md = format_report(report)

    # Add failure analysis from first run with trace
    runs_dir = Path(__file__).parent.parent / "runs"
    trace = []
    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            trace_file = run_dir / "trace.jsonl"
            if trace_file.exists():
                trace = [json.loads(l) for l in trace_file.read_text().splitlines() if l]
                break

    all_fn = [fn for r in all_results for fn in r.get("false_negatives", [])]
    if all_fn:
        custom_gt = json.loads((GROUND_TRUTH_DIR / "custom-idor-lab.json").read_text())
        fa = analyze_failures(all_fn, custom_gt, trace)
        md += "\n\n" + format_failure_report(fa, len(all_fn))

    md_path = REPORTS_DIR / f"report_{run_date}.md"
    md_path.write_text(md)
    print(f"\n[OK] Report saved: {md_path}")
    return md


@click.command()
@click.option("--suite", default="custom", type=click.Choice(["all", "custom", "portswigger"]),
              show_default=True, help="Which suite to run")
@click.option("--generate-report", is_flag=True, help="Generate maturity report after run")
@click.option("--output", default=None, help="Save raw results JSON to file")
def main(suite, generate_report, output):
    """IDOR Hunter Eval Harness."""
    run_date = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    all_results = []

    if suite in ("all", "custom"):
        result = run_custom_suite()
        all_results.append(result)

    if suite in ("all", "portswigger"):
        result = run_portswigger_suite()
        all_results.append(result)

    if output:
        with open(output, "w") as f:
            json.dump(all_results, f, indent=2)

    # Summary
    total_gt = sum(r.get("total_ground_truth", 0) for r in all_results)
    total_tp = sum(len(r.get("true_positives", [])) for r in all_results)
    print(f"\n{'='*50}")
    print(f"TOTAL: {total_tp}/{total_gt} IDORs found ({total_tp/total_gt*100:.1f}% recall)" if total_gt else "No results")

    if generate_report:
        generate_report(all_results, run_date)

    json.dump({"results": all_results, "run_date": run_date}, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
