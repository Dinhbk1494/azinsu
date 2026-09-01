from agent.schemas.finding import Finding


class Memory:
    def __init__(self):
        self.auth_sessions: dict[str, dict] = {}  # label -> {cookies, headers}
        self.discovered_endpoints: list[dict] = []
        self.tested_combinations: set[str] = set()
        self.candidate_idors: list[dict] = []
        self.confirmed_findings: list[Finding] = []
        self.observations: list[str] = []
        self.step_count: int = 0

    def add_session(self, label: str, cookies: dict, headers: dict, user_info: dict | None = None):
        self.auth_sessions[label] = {
            "cookies": cookies,
            "headers": headers,
            "user_info": user_info or {},
        }

    def add_endpoints(self, endpoints: list[dict]):
        seen = {e["url"] + e["method"] for e in self.discovered_endpoints}
        for ep in endpoints:
            key = ep["url"] + ep.get("method", "GET")
            if key not in seen:
                self.discovered_endpoints.append(ep)
                seen.add(key)

    def mark_tested(self, endpoint: str, method: str, param: str, value: str):
        self.tested_combinations.add(f"{method}:{endpoint}:{param}:{value}")

    def is_tested(self, endpoint: str, method: str, param: str, value: str) -> bool:
        return f"{method}:{endpoint}:{param}:{value}" in self.tested_combinations

    def add_candidate(self, candidate: dict):
        self.candidate_idors.append(candidate)

    def add_finding(self, finding: Finding):
        self.confirmed_findings.append(finding)

    def add_observation(self, text: str):
        self.observations.append(text)
        self.step_count += 1

    def get_findings(self) -> list[Finding]:
        return self.confirmed_findings

    def has_completed_goal(self) -> bool:
        return False  # Let max_steps be the terminator for now

    def summary(self) -> str:
        lines = [
            f"Sessions: {list(self.auth_sessions.keys())}",
            f"Discovered endpoints: {len(self.discovered_endpoints)}",
            f"Tested combinations: {len(self.tested_combinations)}",
            f"Candidate IDORs: {len(self.candidate_idors)}",
            f"Confirmed findings: {len(self.confirmed_findings)}",
        ]
        if self.observations:
            lines.append(f"Last observation: {self.observations[-1]}")
        # Include recent endpoint list (first 10)
        for ep in self.discovered_endpoints[:10]:
            lines.append(f"  - {ep.get('method','GET')} {ep.get('url','')}")
        return "\n".join(lines)
