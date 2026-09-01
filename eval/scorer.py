"""Auto-scorer: compare agent findings against ground truth."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScoreReport:
    target: str
    total_ground_truth: int
    true_positives: list[str] = field(default_factory=list)
    false_positives: list[dict] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        tp = len(self.true_positives)
        fp = len(self.false_positives)
        return tp / (tp + fp) if (tp + fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        tp = len(self.true_positives)
        fn = len(self.false_negatives)
        return tp / (tp + fn) if (tp + fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "total_ground_truth": self.total_ground_truth,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


def _normalize_endpoint(ep: str) -> str:
    """Normalize endpoint for fuzzy matching."""
    import re
    # 1. Replace original template params like {user_id} FIRST
    ep = re.sub(r'/\{[^}]+\}', '/{id}', ep)
    # 2. Then replace actual UUIDs in URLs
    ep = re.sub(
        r'/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        '/{uuid}', ep
    )
    # 3. Finally replace numeric segments
    ep = re.sub(r'/\d+', '/{id}', ep)
    ep = ep.rstrip("/").lower()
    return ep


def _match_finding_to_truth(finding: dict, truth: dict) -> bool:
    """Check if a finding matches a ground truth IDOR."""
    finding_ep = _normalize_endpoint(finding.get("endpoint", ""))
    truth_ep = _normalize_endpoint(truth.get("endpoint", ""))

    # Exact method match
    if finding.get("method", "GET").upper() != truth.get("method", "GET").upper():
        return False

    # Endpoint match (exact or normalized)
    if finding_ep == truth_ep:
        return True

    # Allow if one is a prefix of the other (handles template vs actual)
    # Only when endpoint paths share at least 2 segments
    f_parts = [p for p in finding_ep.split("/") if p]
    t_parts = [p for p in truth_ep.split("/") if p]
    if len(f_parts) >= 2 and len(t_parts) >= 2:
        if f_parts[:-1] == t_parts[:-1]:  # Same path prefix, different final segment
            # Same base path family
            if finding.get("vulnerable_param") == truth.get("vulnerable_param"):
                return True

    return False


def score_run(findings: list[dict], ground_truth: dict) -> ScoreReport:
    """Compare agent findings vs ground truth. Returns ScoreReport."""
    target = ground_truth.get("target", "unknown")
    truth_idors = ground_truth.get("idors", [])
    report = ScoreReport(target=target, total_ground_truth=len(truth_idors))

    matched_truth_ids: set[str] = set()

    for finding in findings:
        if not finding.get("confirmed", False) and finding.get("confidence", 0) < 0.5:
            continue  # Skip low-confidence unconfirmed findings

        matched = False
        for truth in truth_idors:
            tid = truth["id"]
            if tid in matched_truth_ids:
                continue
            if _match_finding_to_truth(finding, truth):
                report.true_positives.append(tid)
                matched_truth_ids.add(tid)
                matched = True
                break

        if not matched:
            report.false_positives.append({
                "endpoint": finding.get("endpoint"),
                "method": finding.get("method"),
                "param": finding.get("vulnerable_param"),
            })

    for truth in truth_idors:
        if truth["id"] not in matched_truth_ids:
            report.false_negatives.append(truth["id"])

    return report


def score_by_difficulty(findings: list[dict], ground_truth: dict) -> dict:
    """Break down scores by easy/medium/hard difficulty."""
    truth_idors = ground_truth.get("idors", [])
    by_diff: dict[str, list[dict]] = {"easy": [], "medium": [], "hard": []}
    for t in truth_idors:
        by_diff[t.get("difficulty", "medium")].append(t)

    results = {}
    for diff, truths in by_diff.items():
        subset_gt = {**ground_truth, "idors": truths}
        report = score_run(findings, subset_gt)
        results[diff] = report.to_dict()

    return results
