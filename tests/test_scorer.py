"""Additional scorer tests."""
import pytest
from eval.scorer import score_run, score_by_difficulty, _normalize_endpoint


def test_normalize_endpoint():
    assert _normalize_endpoint("/api/users/123") == "/api/users/{id}"
    assert _normalize_endpoint("/api/docs/550e8400-e29b-41d4-a716-446655440000") == "/api/docs/{uuid}"


def test_by_difficulty():
    findings = [
        {"endpoint": "/api/users/2", "method": "GET", "vulnerable_param": "user_id",
         "param_location": "path", "confirmed": True, "confidence": 0.9}
    ]
    gt = {
        "target": "test",
        "idors": [
            {"id": "EASY-01", "endpoint": "/api/users/{user_id}", "method": "GET",
             "vulnerable_param": "user_id", "param_location": "path", "difficulty": "easy"},
            {"id": "HARD-01", "endpoint": "/api/share/{slug}", "method": "GET",
             "vulnerable_param": "slug", "param_location": "path", "difficulty": "hard"},
        ]
    }
    breakdown = score_by_difficulty(findings, gt)
    assert "easy" in breakdown
    assert "hard" in breakdown
    assert breakdown["easy"]["recall"] == 1.0
    assert breakdown["hard"]["recall"] == 0.0
