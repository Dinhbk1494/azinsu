import json
import os
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent.core.llm_client import LLMClient
from agent.core.memory import Memory
from agent.core.logger import TraceLogger
from agent.tools.auth_login import AuthLoginTool
from agent.tools.endpoint_discover import EndpointDiscoverTool
from agent.tools.id_mutate import IdMutateTool
from agent.tools.auth_compare import AuthCompareTool
from agent.tools.idor_confirm import IdorConfirmTool
from agent.tools.base import set_scope

console = Console()

TOOLS = {
    "auth_login": AuthLoginTool(),
    "endpoint_discover": EndpointDiscoverTool(),
    "id_mutate": IdMutateTool(),
    "auth_compare": AuthCompareTool(),
    "idor_confirm": IdorConfirmTool(),
}


def execute_tool(name: str, args: dict) -> dict:
    tool = TOOLS.get(name)
    if not tool:
        return {"error": f"Unknown tool: {name}"}
    return tool.safe_run(**args)


class Orchestrator:
    def __init__(self, target_url: str, users: list[dict],
                 max_steps: int = 50, model: str | None = None,
                 run_id: str | None = None, scope: list[str] | None = None):
        self.target_url = target_url
        self.users = users
        self.max_steps = max_steps
        self.llm = LLMClient(model=model)
        self.memory = Memory()
        self.logger = TraceLogger(run_id=run_id)

        # Set scope to target URL
        set_scope(scope or [target_url])

    def run(self) -> list[dict]:
        console.print(Panel(f"[bold green]IDOR Hunter Agent[/bold green]\nTarget: {self.target_url}", expand=False))

        messages: list[dict] = []

        # Initial prompt
        user_info = json.dumps(self.users, indent=2)
        initial = (
            f"Target: {self.target_url}\n"
            f"Users available:\n{user_info}\n\n"
            "Start the IDOR hunt. First login as all users, then discover endpoints, "
            "then systematically test for IDORs."
        )
        messages.append({"role": "user", "content": initial})

        for step in range(self.max_steps):
            console.print(f"\n[dim]Step {step+1}/{self.max_steps}[/dim]")

            try:
                thought, tool_call, response = self.llm.plan(self.memory.summary(), messages)
            except Exception as e:
                console.print(f"[red]LLM error: {e}[/red]")
                break

            # Add assistant response to messages
            messages.append({"role": "assistant", "content": response.content})

            if thought:
                console.print(f"[cyan]Thought:[/cyan] {thought[:200]}")

            self.logger.log_thought(step, thought, tool_call)

            if not tool_call:
                # Agent decided to stop
                self.memory.add_observation("Agent completed (no tool call)")
                console.print("[green]Agent completed.[/green]")
                break

            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            console.print(f"[yellow]Tool:[/yellow] {tool_name}({json.dumps(tool_args)[:100]}...)")

            result = execute_tool(tool_name, tool_args)

            self.logger.log_action(step, tool_name, tool_args, result)

            # Update memory based on tool results
            self._update_memory(tool_name, tool_args, result)

            # Add tool result to messages
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result)[:8000],
                    }
                ],
            })

            observation = f"{tool_name} → {self._summarize_result(tool_name, result)}"
            self.memory.add_observation(observation)
            console.print(f"[dim]Result: {observation[:150]}[/dim]")

            if self.memory.has_completed_goal():
                break

        findings = self.memory.get_findings()
        finding_dicts = [f.model_dump() if hasattr(f, 'model_dump') else f for f in findings]

        self.logger.save_findings(finding_dicts)
        self.logger.save_metadata({
            "target": self.target_url,
            "steps": step + 1,
            "findings_count": len(findings),
        })

        console.print(f"\n[bold green]Finished. {len(findings)} confirmed IDORs found.[/bold green]")
        console.print(f"[dim]Trace: {self.logger.run_dir}[/dim]")

        return finding_dicts

    def _update_memory(self, tool_name: str, args: dict, result: dict):
        if tool_name == "auth_login" and result.get("success"):
            label = args.get("credentials", {}).get("email", "user")
            self.memory.add_session(label, result.get("cookies", {}), result.get("headers", {}), result.get("user_info"))

        elif tool_name == "endpoint_discover":
            eps = result.get("endpoints", [])
            self.memory.add_endpoints(eps)

        elif tool_name == "auth_compare" and result.get("suggests_idor"):
            self.memory.add_candidate({
                "url": args.get("url"),
                "suggests_idor": True,
                "confidence": result.get("confidence", 0),
                "differences": result.get("differences", []),
            })

        elif tool_name == "idor_confirm" and result.get("confirmed"):
            from agent.schemas.finding import Finding, Evidence, HttpRequest, HttpResponse
            import uuid as _uuid
            candidate = args.get("candidate", {})
            evidence_data = result.get("evidence", {}) or {}
            try:
                finding = Finding(
                    id=f"IDOR-{_uuid.uuid4().hex[:6].upper()}",
                    target_url=self.target_url,
                    endpoint=candidate.get("url", ""),
                    method=candidate.get("method", "GET"),
                    vulnerable_param=candidate.get("vulnerable_param", ""),
                    param_location=candidate.get("param_location", "path"),
                    idor_type=self._classify_idor_type(candidate),
                    description=f"IDOR via {candidate.get('vulnerable_param')} in {candidate.get('param_location')}",
                    confidence=result.get("confidence", 0.8),
                    evidence=Evidence(
                        unauthorized_data=evidence_data.get("unauthorized_data", {}),
                        user_b_fields_found=evidence_data.get("user_b_fields_found", []),
                        raw_response_excerpt=evidence_data.get("raw_response_excerpt", ""),
                    ),
                    poc_request=HttpRequest(**(result.get("poc_request") or {"method": "GET", "url": candidate.get("url", "")})),
                    poc_response=HttpResponse(**(result.get("poc_response") or {"status_code": 200})),
                    confirmed=True,
                )
                self.memory.add_finding(finding)
                console.print(f"[bold red]CONFIRMED IDOR: {candidate.get('url')} [{candidate.get('vulnerable_param')}][/bold red]")
            except Exception as e:
                console.print(f"[red]Failed to save finding: {e}[/red]")

    def _classify_idor_type(self, candidate: dict) -> str:
        location = candidate.get("param_location", "path")
        param = candidate.get("vulnerable_param", "")
        orig = candidate.get("original_value", "")

        if location == "path" and str(orig).isdigit():
            return "numeric_id_in_path"
        elif location == "query":
            return "numeric_id_in_query"
        elif location == "body":
            return "id_in_request_body"
        elif location == "header":
            return "id_in_custom_header"
        elif location == "cookie":
            return "id_in_cookie"
        return "unknown_idor"

    def _summarize_result(self, tool_name: str, result: dict) -> str:
        if "error" in result:
            return f"ERROR: {result['error']}"
        if tool_name == "auth_login":
            return f"success={result.get('success')} cookies={list(result.get('cookies', {}).keys())}"
        if tool_name == "endpoint_discover":
            return f"{len(result.get('endpoints', []))} endpoints, {len(result.get('parameters_with_id_indicators', []))} ID params"
        if tool_name == "id_mutate":
            return f"{len(result.get('mutations', []))} mutations generated"
        if tool_name == "auth_compare":
            return f"suggests_idor={result.get('suggests_idor')} confidence={result.get('confidence', 0):.2f}"
        if tool_name == "idor_confirm":
            return f"confirmed={result.get('confirmed')} confidence={result.get('confidence', 0):.2f}"
        return str(result)[:100]
