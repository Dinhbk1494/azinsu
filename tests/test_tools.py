"""Unit tests for agent tools."""
import pytest
from unittest.mock import patch, MagicMock


class TestIdMutate:
    def test_sequential_increment(self):
        from agent.tools.id_mutate import IdMutateTool
        tool = IdMutateTool()
        result = tool.run(original_value="5", strategies=["sequential_increment"])
        values = [m["value"] for m in result["mutations"]]
        assert "6" in values
        assert "7" in values
        assert "5" not in values  # Original excluded

    def test_base64_mutate(self):
        from agent.tools.id_mutate import IdMutateTool
        import base64
        tool = IdMutateTool()
        # Encode "1" as base64
        encoded = base64.b64encode(b"1").decode()
        result = tool.run(original_value=encoded, strategies=["decode_then_mutate"])
        assert len(result["mutations"]) > 0
        # Should have decoded and re-encoded
        for m in result["mutations"]:
            assert m["strategy"] == "decode_then_mutate"

    def test_user_b_ids(self):
        from agent.tools.id_mutate import IdMutateTool
        tool = IdMutateTool()
        result = tool.run(original_value="1", strategies=["user_b_ids"], user_b_known_ids=["42", "99"])
        values = [m["value"] for m in result["mutations"]]
        assert "42" in values
        assert "99" in values

    def test_no_duplicates(self):
        from agent.tools.id_mutate import IdMutateTool
        tool = IdMutateTool()
        result = tool.run(original_value="1")
        values = [m["value"] for m in result["mutations"]]
        assert len(values) == len(set(values)), "Duplicate mutations found"

    def test_hex_mutate(self):
        from agent.tools.id_mutate import IdMutateTool
        tool = IdMutateTool()
        result = tool.run(original_value="10", strategies=["hex_mutate"])
        values = [m["value"] for m in result["mutations"]]
        assert "0xb" in values or "0x9" in values  # hex(11) or hex(9)


class TestScorer:
    def test_exact_match(self):
        from eval.scorer import score_run
        findings = [
            {"endpoint": "/api/users/2/profile", "method": "GET",
             "vulnerable_param": "user_id", "param_location": "path",
             "confirmed": True, "confidence": 0.9}
        ]
        gt = {
            "target": "test",
            "idors": [
                {"id": "TEST-01", "endpoint": "/api/users/{user_id}/profile",
                 "method": "GET", "vulnerable_param": "user_id", "param_location": "path"}
            ]
        }
        report = score_run(findings, gt)
        assert "TEST-01" in report.true_positives
        assert len(report.false_negatives) == 0

    def test_false_negative(self):
        from eval.scorer import score_run
        findings = []
        gt = {
            "target": "test",
            "idors": [
                {"id": "TEST-01", "endpoint": "/api/users/1", "method": "GET",
                 "vulnerable_param": "id", "param_location": "path"}
            ]
        }
        report = score_run(findings, gt)
        assert "TEST-01" in report.false_negatives
        assert report.recall == 0.0

    def test_false_positive(self):
        from eval.scorer import score_run
        findings = [
            {"endpoint": "/api/nonexistent", "method": "GET",
             "vulnerable_param": "id", "param_location": "path",
             "confirmed": True, "confidence": 0.9}
        ]
        gt = {"target": "test", "idors": []}
        report = score_run(findings, gt)
        assert len(report.false_positives) == 1
        assert report.precision == 0.0

    def test_precision_recall(self):
        from eval.scorer import score_run
        findings = [
            {"endpoint": "/api/users/2", "method": "GET", "vulnerable_param": "id",
             "param_location": "path", "confirmed": True, "confidence": 0.9},
            {"endpoint": "/api/fake", "method": "GET", "vulnerable_param": "id",
             "param_location": "path", "confirmed": True, "confidence": 0.9},
        ]
        gt = {
            "target": "test",
            "idors": [
                {"id": "A", "endpoint": "/api/users/{id}", "method": "GET",
                 "vulnerable_param": "id", "param_location": "path"},
                {"id": "B", "endpoint": "/api/orders/{id}", "method": "GET",
                 "vulnerable_param": "id", "param_location": "path"},
            ]
        }
        report = score_run(findings, gt)
        assert report.precision == 0.5  # 1 TP / 2 findings
        assert report.recall == 0.5    # 1 TP / 2 truths


class TestMaturityCalculator:
    def test_level_classification(self):
        from eval.maturity_calculator import calculate_maturity
        results = [
            {"target": "test", "total_ground_truth": 10,
             "true_positives": ["A"] * 9, "false_positives": ["X"],
             "false_negatives": ["B"], "recall": 0.9, "precision": 0.9, "f1": 0.9}
        ]
        report = calculate_maturity(results)
        assert report.level == "Senior"

    def test_junior_level(self):
        from eval.maturity_calculator import calculate_maturity
        results = [
            {"target": "test", "total_ground_truth": 10,
             "true_positives": ["A"] * 4, "false_positives": [],
             "false_negatives": ["B"] * 6, "recall": 0.4, "precision": 1.0, "f1": 0.57}
        ]
        report = calculate_maturity(results)
        assert report.level in ("Junior", "Mid-level")


class TestFailureAnalyzer:
    def test_discovery_gap(self):
        from eval.failure_analyzer import analyze_failures
        gt = {
            "idors": [
                {"id": "TEST-01", "endpoint": "/api/secret", "type": "numeric_id_in_path",
                 "param_location": "path"}
            ]
        }
        trace = []  # Empty trace — agent did nothing
        analysis = analyze_failures(["TEST-01"], gt, trace)
        assert analysis.failures[0].category == "DISCOVERY_GAP"

    def test_category_counts(self):
        from eval.failure_analyzer import analyze_failures
        gt = {
            "idors": [
                {"id": "TEST-01", "endpoint": "/ep1", "type": "numeric_id_in_path", "param_location": "path"},
                {"id": "TEST-02", "endpoint": "/ep2", "type": "base64_encoded_id", "param_location": "query"},
            ]
        }
        analysis = analyze_failures(["TEST-01", "TEST-02"], gt, [])
        assert sum(analysis.category_counts.values()) == 2
