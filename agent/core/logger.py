import json
import os
import uuid
from datetime import datetime
from pathlib import Path


class TraceLogger:
    def __init__(self, run_id: str | None = None, runs_dir: str = "runs"):
        self.run_id = run_id or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.run_dir = Path(runs_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.trace_path = self.run_dir / "trace.jsonl"
        self.findings_path = self.run_dir / "findings.json"
        self.tool_calls_path = self.run_dir / "tool_calls.jsonl"
        self.metadata_path = self.run_dir / "metadata.json"

        self._meta: dict = {}

    def _append(self, path: Path, record: dict):
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def log_thought(self, step: int, thought: str, tool_call: dict | None):
        self._append(self.trace_path, {
            "type": "thought",
            "step": step,
            "timestamp": datetime.utcnow().isoformat(),
            "thought": thought,
            "tool_call": tool_call,
        })

    def log_action(self, step: int, tool_name: str, tool_input: dict, result: dict):
        record = {
            "type": "action",
            "step": step,
            "timestamp": datetime.utcnow().isoformat(),
            "tool": tool_name,
            "input": tool_input,
            "result": result,
        }
        self._append(self.trace_path, record)
        self._append(self.tool_calls_path, record)

    def log_observation(self, step: int, observation: str):
        self._append(self.trace_path, {
            "type": "observation",
            "step": step,
            "timestamp": datetime.utcnow().isoformat(),
            "observation": observation,
        })

    def log_http(self, method: str, url: str, status: int, elapsed_ms: float):
        self._append(self.trace_path, {
            "type": "http",
            "timestamp": datetime.utcnow().isoformat(),
            "method": method,
            "url": url,
            "status": status,
            "elapsed_ms": elapsed_ms,
        })

    def save_findings(self, findings: list):
        with open(self.findings_path, "w") as f:
            json.dump([f if isinstance(f, dict) else f.model_dump() for f in findings], f, indent=2)

    def save_metadata(self, meta: dict):
        self._meta.update(meta)
        self._meta["run_id"] = self.run_id
        self._meta["timestamp"] = datetime.utcnow().isoformat()
        with open(self.metadata_path, "w") as f:
            json.dump(self._meta, f, indent=2)

    def read_trace(self) -> list[dict]:
        if not self.trace_path.exists():
            return []
        records = []
        with open(self.trace_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
