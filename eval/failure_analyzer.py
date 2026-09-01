"""Failure Analyzer: categorize why each IDOR was missed."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


CATEGORIES = {
    "DISCOVERY_GAP": "Agent never found the vulnerable endpoint",
    "MUTATION_GAP": "Agent found endpoint but tried wrong ID mutations",
    "COMPARISON_GAP": "Agent tried mutation but didn't recognize unauthorized access",
    "CONFIRMATION_GAP": "Agent suspected IDOR but didn't confirm",
    "REASONING_GAP": "Agent made wrong logical inference",
}

IMPROVEMENT_TEMPLATES = {
    "DISCOVERY_GAP": [
        ("missed_graphql", "Improve endpoint_discover to probe /graphql, /api/graphql via OPTIONS"),
        ("missed_js_api", "Add regex mining of JS files for fetch/axios calls"),
        ("missed_depth", "Increase crawler max_depth from 3 to 5"),
        ("no_auth_endpoints", "Add probe of common unauthenticated paths (/uploads/, /share/)"),
    ],
    "MUTATION_GAP": [
        ("no_encoding", "Add auto-detection and mutation of base64/hex encoded IDs"),
        ("no_method_variation", "Always try all HTTP methods (GET/POST/PUT/DELETE/PATCH) on ID endpoints"),
        ("no_header_ids", "Add header-based ID mutation (X-User-Id, X-Account-Id)"),
        ("no_cookie_ids", "Add cookie-based ID mutation"),
        ("narrow_enumeration", "Expand sequential enumeration range from ±3 to ±100"),
    ],
    "COMPARISON_GAP": [
        ("subtle_diff", "Improve response diffing — compare all JSON fields, not just status+length"),
        ("empty_200", "Handle 200 OK with empty body as potential IDOR (not confirmed, but flag)"),
        ("size_threshold", "Lower response size difference threshold from 50 to 10 bytes"),
    ],
    "CONFIRMATION_GAP": [
        ("no_extraction", "Always extract User B's known fields from response as evidence"),
        ("no_rerun", "Run confirmation request 3 times to filter flakiness"),
        ("no_user_b_data", "Pass more User B fields (email, name, phone) to idor_confirm"),
    ],
    "REASONING_GAP": [
        ("rate_limit_confusion", "Add pattern recognition: 429 = rate limit (not auth), retry later"),
        ("session_expiry", "Detect session expiry pattern and re-login automatically"),
        ("irrelevant_endpoints", "Add endpoint scoring to prioritize ID-containing endpoints"),
    ],
}


@dataclass
class FailureEntry:
    test_id: str
    category: str
    sub_cause: str
    description: str
    suggested_fix: str


@dataclass
class FailureAnalysis:
    failures: list[FailureEntry] = field(default_factory=list)
    category_counts: dict = field(default_factory=dict)
    top_improvements: list[dict] = field(default_factory=list)


def _endpoint_was_requested(trace: list[dict], endpoint_pattern: str) -> bool:
    """Check if the endpoint was ever requested in the trace."""
    import re
    pattern = re.sub(r'\{[^}]+\}', r'[^/]+', endpoint_pattern)
    for entry in trace:
        if entry.get("type") == "http":
            url = entry.get("url", "")
            if re.search(pattern, url):
                return True
        if entry.get("type") == "action":
            result = entry.get("result", {})
            # Check tool calls for this endpoint
            inp = entry.get("input", {})
            url = str(inp.get("url", "") or inp.get("base_url", ""))
            if re.search(pattern, url):
                return True
    return False


def _mutation_was_tried(trace: list[dict], truth: dict) -> bool:
    """Check if ID mutation was attempted for this endpoint."""
    for entry in trace:
        if entry.get("type") == "action" and entry.get("tool") == "id_mutate":
            return True
        if entry.get("type") == "action" and entry.get("tool") == "auth_compare":
            return True
    return False


def _idor_was_flagged(trace: list[dict], truth: dict) -> bool:
    """Check if agent flagged a candidate IDOR."""
    for entry in trace:
        if entry.get("type") == "action" and entry.get("tool") == "idor_confirm":
            return True
        if entry.get("type") == "thought":
            thought = entry.get("thought", "").lower()
            if "idor" in thought or "unauthorized" in thought or "candidate" in thought:
                return True
    return False


def _auth_compare_suggested_idor(trace: list[dict]) -> bool:
    for entry in trace:
        if entry.get("type") == "action" and entry.get("tool") == "auth_compare":
            result = entry.get("result", {})
            if result.get("suggests_idor"):
                return True
    return False


def categorize_failure(truth: dict, trace: list[dict]) -> tuple[str, str]:
    endpoint = truth.get("endpoint", "")

    if not _endpoint_was_requested(trace, endpoint):
        idor_type = truth.get("type", "")
        if "graphql" in idor_type:
            return "DISCOVERY_GAP", "missed_graphql"
        elif "slug" in idor_type or "predictable" in idor_type:
            return "DISCOVERY_GAP", "no_auth_endpoints"
        return "DISCOVERY_GAP", "missed_js_api"

    if not _mutation_was_tried(trace, truth):
        idor_type = truth.get("type", "")
        if "base64" in idor_type or "hex" in idor_type:
            return "MUTATION_GAP", "no_encoding"
        elif "header" in truth.get("param_location", ""):
            return "MUTATION_GAP", "no_header_ids"
        elif "cookie" in truth.get("param_location", ""):
            return "MUTATION_GAP", "no_cookie_ids"
        elif "method" in idor_type:
            return "MUTATION_GAP", "no_method_variation"
        return "MUTATION_GAP", "narrow_enumeration"

    if not _auth_compare_suggested_idor(trace):
        return "COMPARISON_GAP", "subtle_diff"

    if not _idor_was_flagged(trace, truth):
        return "CONFIRMATION_GAP", "no_extraction"

    return "REASONING_GAP", "irrelevant_endpoints"


def analyze_failures(
    false_negatives: list[str],
    ground_truth: dict,
    trace: list[dict],
) -> FailureAnalysis:
    analysis = FailureAnalysis()
    category_counts: dict[str, int] = {c: 0 for c in CATEGORIES}

    truth_by_id = {t["id"]: t for t in ground_truth.get("idors", [])}

    for fn_id in false_negatives:
        truth = truth_by_id.get(fn_id, {"id": fn_id, "endpoint": "", "type": ""})
        category, sub_cause = categorize_failure(truth, trace)
        category_counts[category] = category_counts.get(category, 0) + 1

        # Find fix suggestion
        fixes = IMPROVEMENT_TEMPLATES.get(category, [])
        fix_text = next((f[1] for f in fixes if f[0] == sub_cause), "Review trace for specific failure")

        analysis.failures.append(FailureEntry(
            test_id=fn_id,
            category=category,
            sub_cause=sub_cause,
            description=CATEGORIES.get(category, ""),
            suggested_fix=fix_text,
        ))

    analysis.category_counts = category_counts

    # Rank improvements by count
    improvements_by_fix: dict[str, int] = {}
    for f in analysis.failures:
        improvements_by_fix[f.suggested_fix] = improvements_by_fix.get(f.suggested_fix, 0) + 1

    analysis.top_improvements = [
        {"fix": fix, "expected_impact": count, "affected_tests": count}
        for fix, count in sorted(improvements_by_fix.items(), key=lambda x: -x[1])
    ]

    return analysis


def format_failure_report(analysis: FailureAnalysis, total_failures: int) -> str:
    lines = [
        "## Failure Analysis",
        "",
        f"Total failures: {total_failures}",
    ]
    total = sum(analysis.category_counts.values())
    for cat, count in sorted(analysis.category_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            pct = count / total * 100 if total > 0 else 0
            lines.append(f"- {cat}: {count} ({pct:.0f}%)")

    lines.append("")
    lines.append("### Top Improvements (by expected impact)")
    for i, imp in enumerate(analysis.top_improvements[:5], 1):
        lines.append(f"\n**#{i}**: {imp['fix']}")
        lines.append(f"Expected impact: +{imp['expected_impact']} tests")

    return "\n".join(lines)
