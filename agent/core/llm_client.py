import os
import json
import anthropic
from pathlib import Path


SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "system.md").read_text()
STRATEGIES = (Path(__file__).parent.parent / "prompts" / "strategies.md").read_text()

TOOLS_SCHEMA = [
    {
        "name": "auth_login",
        "description": "Authenticate as a user and obtain session credentials (cookies/token).",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "login_endpoint": {"type": "string", "default": "/api/login"},
                "method": {"type": "string", "default": "POST"},
                "credentials": {"type": "object"},
                "auth_type": {"type": "string", "enum": ["form", "json", "basic", "oauth"], "default": "json"},
            },
            "required": ["base_url", "credentials"],
        },
    },
    {
        "name": "endpoint_discover",
        "description": "Crawl target and find endpoints with identifier parameters (likely IDOR candidates).",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "auth": {"type": "object", "description": "Dict with 'cookies' and/or 'headers' keys"},
                "max_depth": {"type": "integer", "default": 3},
                "include_graphql": {"type": "boolean", "default": True},
            },
            "required": ["base_url"],
        },
    },
    {
        "name": "id_mutate",
        "description": "Generate ID variations to test (sequential, encoded, UUID, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "original_value": {"type": "string"},
                "strategies": {"type": "array", "items": {"type": "string"}},
                "user_b_known_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["original_value"],
        },
    },
    {
        "name": "auth_compare",
        "description": "Make the same request with multiple auth contexts and compare responses to detect unauthorized access.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "default": "GET"},
                "path_params": {"type": "object"},
                "query_params": {"type": "object"},
                "body": {"type": "object"},
                "request_headers": {"type": "object"},
                "auth_contexts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "cookies": {"type": "object"},
                            "headers": {"type": "object"},
                        },
                    },
                },
            },
            "required": ["url", "auth_contexts"],
        },
    },
    {
        "name": "idor_confirm",
        "description": "Confirm an IDOR candidate by verifying that User A's session can access User B's data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string"},
                        "vulnerable_param": {"type": "string"},
                        "param_location": {"type": "string"},
                        "original_value": {"type": "string"},
                        "mutated_value": {"type": "string"},
                        "param_in_query": {"type": "object"},
                        "param_in_body": {"type": "object"},
                        "param_in_headers": {"type": "object"},
                    },
                    "required": ["url", "method", "vulnerable_param", "param_location", "original_value", "mutated_value"],
                },
                "user_a_auth": {"type": "object"},
                "user_b_auth": {"type": "object"},
                "user_b_known_data": {"type": "object"},
            },
            "required": ["candidate", "user_a_auth", "user_b_auth"],
        },
    },
]


class LLMClient:
    def __init__(self, model: str | None = None):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.system = SYSTEM_PROMPT + "\n\n" + STRATEGIES

    def plan(self, memory_summary: str, messages: list[dict]) -> tuple[str, dict | None]:
        full_messages = messages.copy()

        if not full_messages or full_messages[-1]["role"] != "user":
            full_messages.append({
                "role": "user",
                "content": f"Current state:\n{memory_summary}\n\nContinue the IDOR hunt. Use a tool or report completion.",
            })

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.system,
            tools=TOOLS_SCHEMA,
            messages=full_messages,
        )

        thought = ""
        tool_call = None

        for block in response.content:
            if block.type == "text":
                thought += block.text
            elif block.type == "tool_use":
                tool_call = {
                    "name": block.name,
                    "args": block.input,
                    "id": block.id,
                }

        return thought, tool_call, response
