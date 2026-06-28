"""Failure analyzer tests."""
import pytest
from eval.failure_analyzer import analyze_failures, categorize_failure, format_failure_report


def test_empty_failures():
    gt = {"idors": []}
    analysis = analyze_failures([], gt, [])
    assert len(analysis.failures) == 0


def test_improvement_ranking():
    gt = {
        "idors": [
            {"id": f"TEST-{i:02d}", "endpoint": f"/ep{i}", "type": "base64_encoded_id",
             "param_location": "query"}
            for i in range(1, 4)
        ]
    }
    # Pass IDs through HTTP requests in trace to move past DISCOVERY_GAP
    trace = [
        {"type": "http", "url": f"/ep{i}", "status": 200}
        for i in range(1, 4)
    ]
    analysis = analyze_failures([f"TEST-{i:02d}" for i in range(1, 4)], gt, trace)
    # Should have improvements
    assert len(analysis.top_improvements) > 0
    # First improvement should have highest expected impact
    assert analysis.top_improvements[0]["expected_impact"] >= analysis.top_improvements[-1]["expected_impact"]


def test_format_report():
    gt = {"idors": [
        {"id": "TEST-01", "endpoint": "/ep1", "type": "numeric_id_in_path", "param_location": "path"}
    ]}
    analysis = analyze_failures(["TEST-01"], gt, [])
    report = format_failure_report(analysis, 1)
    assert "Failure Analysis" in report
    assert "DISCOVERY_GAP" in report or "MUTATION_GAP" in report
