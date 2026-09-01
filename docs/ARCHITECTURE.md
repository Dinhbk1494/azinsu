# Architecture

## System Components

```
idor-hunter-agent/
├── agent/          # Core AI agent
│   ├── core/       # LLM client, orchestrator, memory, logger
│   ├── tools/      # 5 specialized tools
│   ├── prompts/    # System + strategy prompts
│   └── schemas/    # Pydantic models
├── lab/            # Vulnerable targets
│   ├── custom-idor-lab/   # 20 IDOR variations (Flask)
│   ├── ground_truth/      # JSON ground truth per target
│   └── scripts/           # Setup, reset, verify
├── eval/           # Evaluation harness
│   ├── scorer.py           # Precision/recall calculation
│   ├── maturity_calculator.py  # Score + level
│   ├── failure_analyzer.py     # Root cause analysis
│   └── adapters/           # Target-specific runners
├── runs/           # Run outputs (JSONL traces)
├── reports/        # Generated Markdown reports
└── tests/          # Unit tests
```

## Agent Loop (ReAct)

```
User gives: target URL + user credentials
     ↓
1. THINK  → LLM picks next tool
2. ACT    → Execute tool (rate-limited, scope-checked)
3. OBSERVE → Update memory
4. Repeat until max_steps or goal reached
     ↓
Output: confirmed IDOR findings JSON
```

## 5 Tools

| Tool | Purpose |
|------|---------|
| `auth_login` | Authenticate, get session token/cookies |
| `endpoint_discover` | Crawl app, find endpoints with ID params |
| `id_mutate` | Generate 18+ ID mutation strategies |
| `auth_compare` | Test same endpoint with multiple auth contexts |
| `idor_confirm` | Extract evidence that User A sees User B's data |

## Safety Controls

- All HTTP requests go through `checked_request()` → scope check + rate limit
- Default rate limit: 1 req/sec (configurable via `RATE_LIMIT` env var)
- Scope is set to target URL at startup; requests to other domains throw `ScopeViolation`
- Bug bounty adapter requires explicit `automation_allowed: true` flag
- Every HTTP request is logged to `runs/<id>/trace.jsonl`
