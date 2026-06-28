# IDOR Hunter Agent

**⚠️ FOR AUTHORIZED SECURITY TESTING ONLY ⚠️**

An AI agent specialized in finding IDOR (Insecure Direct Object Reference) vulnerabilities, with a full evaluation harness to measure agent maturity vs. senior pentester baseline.

## Quick Start

```bash
# 1. Install dependencies
pip install -e .
playwright install chromium

# 2. Set up environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 3. Start the lab
make lab-up

# 4. Verify all IDORs are in place
make verify-truth

# 5. Run the agent on custom lab
make agent-run TARGET=http://localhost:8080 USERS=lab/users.json

# 6. Run full eval harness
make eval-custom

# 7. Generate maturity report
make report
```

## Lab Targets

| Target | URL | IDORs |
|--------|-----|-------|
| Custom IDOR Lab | http://localhost:8080 | 20 (easy/medium/hard) |
| VAmPI | http://localhost:5000 | 2+ |
| OWASP Juice Shop | http://localhost:3000 | 2+ |

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 5 Agent Tools

| Tool | Purpose |
|------|---------|
| `auth_login` | Authenticate users |
| `endpoint_discover` | Find IDOR-prone endpoints |
| `id_mutate` | Generate 18+ ID mutations |
| `auth_compare` | Compare responses across auth contexts |
| `idor_confirm` | Extract concrete evidence |

## Eval Harness

```bash
make eval-custom      # Custom lab (20 IDORs)
make eval-portswigger # PortSwigger AC labs (13)
make eval             # All suites
make senior-baseline  # Record senior pentester results
make report           # Generate maturity report
```

## Maturity Levels

| Score | Level |
|-------|-------|
| 80-100 | Senior |
| 60-79 | Mid-level |
| 35-59 | Junior |
| 0-34 | Below Junior |

## Safety

- All requests are rate-limited (default: 1 req/sec)
- Scope checking blocks requests to out-of-scope targets
- Bug bounty adapter requires explicit `automation_allowed: true`
- Full audit log written to `runs/<id>/trace.jsonl`

## Legal

This tool is for **authorized security testing only**. Use only against:
- Your own systems
- Explicitly consented targets
- Bug bounty programs that allow automation (within scope)

Never run against systems without written permission.
