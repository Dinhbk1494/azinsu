#!/usr/bin/env python3
"""Senior baseline test runner — interactive CLI for recording senior pentester results."""
import json
import time
from pathlib import Path
from datetime import datetime

GROUND_TRUTH_DIR = Path(__file__).parent.parent.parent / "lab" / "ground_truth"
BASELINE_FILE = Path(__file__).parent / "senior_baseline.json"


def main():
    print("=" * 60)
    print("IDOR Hunter - Senior Baseline Test Protocol")
    print("=" * 60)
    print("\nThis tool records the senior pentester's results for the 48-test benchmark.")
    print("Instructions:")
    print("  - For each test, attempt to find the IDOR using Burp Suite + manual testing")
    print("  - Record whether solved, time taken, and tools used")
    print("  - Time limit: 15min (easy), 30min (medium), 45min (hard)")
    print()

    pentester_id = input("Pentester ID (or alias): ").strip()
    experience = input("Experience level (e.g. '8 years, OSCP'): ").strip()

    gt = json.loads((GROUND_TRUTH_DIR / "custom-idor-lab.json").read_text())
    idors = gt["idors"]

    results = []

    for idor in idors:
        print(f"\n{'='*50}")
        print(f"Test: {idor['id']}")
        print(f"Type: {idor['type']}")
        print(f"Endpoint: {idor['method']} {idor['endpoint']}")
        print(f"Difficulty: {idor['difficulty']}")
        print(f"Description: {idor['description']}")
        print()

        start = time.time()
        input("Press Enter when you START this test...")
        start_time = time.time()

        solved_str = input("Solved? (y/n): ").strip().lower()
        solved = solved_str == "y"

        elapsed = int(time.time() - start_time)

        tools = input("Tools used (comma-separated, e.g. 'burp_suite,manual'): ").strip()
        approach = input("Brief approach (1-2 sentences): ").strip()

        results.append({
            "test_id": idor["id"],
            "solved": solved,
            "time_seconds": elapsed,
            "tools_used": [t.strip() for t in tools.split(",")],
            "approach": approach,
            "difficulty": idor["difficulty"],
        })

        status = "SOLVED" if solved else "FAILED"
        print(f"[{status}] {elapsed}s")

    solved_count = sum(1 for r in results if r["solved"])
    total = len(results)
    avg_time = sum(r["time_seconds"] for r in results if r["solved"]) / solved_count if solved_count else 0

    baseline = {
        "pentester_id": pentester_id,
        "experience": experience,
        "test_date": datetime.utcnow().isoformat(),
        "results": results,
        "summary": {
            "total_tests": total,
            "solved": solved_count,
            "solve_rate": solved_count / total if total else 0,
            "avg_time_per_solve": int(avg_time),
        },
    }

    BASELINE_FILE.write_text(json.dumps(baseline, indent=2))
    print(f"\n{'='*50}")
    print(f"Senior Baseline: {solved_count}/{total} ({solved_count/total*100:.1f}%)")
    print(f"Avg time per solve: {avg_time:.0f}s")
    print(f"Saved to: {BASELINE_FILE}")


if __name__ == "__main__":
    main()
