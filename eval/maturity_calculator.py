"""Calculate agent maturity score and level."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class MaturityReport:
    total_tests: int
    total_found: int
    total_fp: int
    precision: float
    recall: float
    f1: float
    per_tier: dict  # {suite_name: {solved, total, recall}}
    per_type: dict  # {idor_type: {solved, total}}
    score: float    # 0-100
    level: str      # Junior/Mid-level/Senior
    senior_comparison: dict | None = None


def calculate_maturity(all_results: list[dict], senior_results: dict | None = None) -> MaturityReport:
    """
    all_results: list of per-suite result dicts with keys:
      {suite, total_ground_truth, true_positives, false_positives, false_negatives, recall, precision, f1}
    """
    total_tests = sum(r.get("total_ground_truth", 0) for r in all_results)
    total_found = sum(len(r.get("true_positives", [])) for r in all_results)
    total_fp = sum(len(r.get("false_positives", [])) for r in all_results)
    total_fn = sum(len(r.get("false_negatives", [])) for r in all_results)

    precision = total_found / (total_found + total_fp) if (total_found + total_fp) > 0 else 0.0
    recall = total_found / total_tests if total_tests > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    per_tier = {}
    for r in all_results:
        suite = r.get("target", r.get("suite", "unknown"))
        per_tier[suite] = {
            "solved": len(r.get("true_positives", [])),
            "total": r.get("total_ground_truth", 0),
            "recall": r.get("recall", 0),
        }

    # Score formula: 60% recall + 30% precision + 10% bonus for hard IDORs
    score = (recall * 60) + (precision * 30) + _hard_idor_bonus(all_results)
    score = min(100.0, score)

    level = _classify_level(score, recall)

    senior_comparison = None
    if senior_results:
        senior_recall = senior_results.get("solve_rate", 0.94)
        ratio = recall / senior_recall if senior_recall > 0 else 0.0
        senior_comparison = {
            "agent_recall": recall,
            "senior_recall": senior_recall,
            "relative_performance": round(ratio, 3),
            "gap": round(senior_recall - recall, 3),
            "verdict": _level_by_ratio(ratio),
        }

    return MaturityReport(
        total_tests=total_tests,
        total_found=total_found,
        total_fp=total_fp,
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        per_tier=per_tier,
        per_type={},
        score=round(score, 1),
        level=level,
        senior_comparison=senior_comparison,
    )


def _hard_idor_bonus(results: list[dict]) -> float:
    hard_solved = 0
    hard_total = 0
    for r in results:
        for tp in r.get("true_positives", []):
            if "hard" in tp.lower() or any(n in tp for n in ["15", "16", "17", "18", "19", "20"]):
                hard_solved += 1
                hard_total += 1
        for fn in r.get("false_negatives", []):
            if "hard" in fn.lower() or any(n in fn for n in ["15", "16", "17", "18", "19", "20"]):
                hard_total += 1
    if hard_total == 0:
        return 0.0
    return (hard_solved / hard_total) * 10


def _classify_level(score: float, recall: float) -> str:
    if score >= 80 and recall >= 0.85:
        return "Senior"
    elif score >= 60 and recall >= 0.65:
        return "Mid-level"
    elif score >= 35 and recall >= 0.40:
        return "Junior"
    return "Below Junior"


def _level_by_ratio(ratio: float) -> str:
    if ratio >= 0.90:
        return "Senior"
    elif ratio >= 0.70:
        return "Mid-level"
    elif ratio >= 0.40:
        return "Junior"
    return "Below Junior"


def format_report(report: MaturityReport) -> str:
    lines = [
        "# IDOR Hunter Agent — Maturity Report",
        "",
        f"## Summary",
        f"- **Level**: {report.level}",
        f"- **Score**: {report.score}/100",
        f"- **Total tests**: {report.total_tests}",
        f"- **Found**: {report.total_found} ({report.recall*100:.1f}% recall)",
        f"- **False positives**: {report.total_fp}",
        f"- **Precision**: {report.precision*100:.1f}%",
        f"- **F1**: {report.f1:.3f}",
        "",
        "## Per-Suite Breakdown",
        "| Suite | Solved | Total | Recall |",
        "|-------|--------|-------|--------|",
    ]
    for suite, data in report.per_tier.items():
        lines.append(f"| {suite} | {data['solved']} | {data['total']} | {data['recall']*100:.1f}% |")

    if report.senior_comparison:
        sc = report.senior_comparison
        lines += [
            "",
            "## vs Senior Pentester",
            f"- **Agent recall**: {sc['agent_recall']*100:.1f}%",
            f"- **Senior recall**: {sc['senior_recall']*100:.1f}%",
            f"- **Relative performance**: {sc['relative_performance']*100:.1f}% of senior",
            f"- **Gap**: {sc['gap']*100:.1f}% points",
            f"- **Verdict**: {sc['verdict']}",
        ]

    return "\n".join(lines)
