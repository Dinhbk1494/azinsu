#!/usr/bin/env python3
import json
import sys
import os
import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.option("--target", required=True, help="Target base URL (e.g. http://localhost:8080)")
@click.option("--users", required=True, type=click.Path(exists=True), help="Path to users JSON file")
@click.option("--max-steps", default=50, show_default=True, help="Maximum agent steps")
@click.option("--model", default=None, help="Override LLM model")
@click.option("--run-id", default=None, help="Custom run ID")
@click.option("--scope", multiple=True, help="Allowed URL prefixes (repeatable). Defaults to target.")
@click.option("--output", default=None, help="Save findings JSON to file")
def cli(target, users, max_steps, model, run_id, scope, output):
    """IDOR Hunter Agent — find IDOR vulnerabilities autonomously."""
    from agent.core.orchestrator import Orchestrator

    with open(users) as f:
        users_data = json.load(f)

    scope_list = list(scope) if scope else [target]

    orch = Orchestrator(
        target_url=target,
        users=users_data,
        max_steps=max_steps,
        model=model,
        run_id=run_id,
        scope=scope_list,
    )

    findings = orch.run()

    if output:
        with open(output, "w") as f:
            json.dump(findings, f, indent=2)
        click.echo(f"Findings saved to {output}")
    else:
        click.echo(json.dumps(findings, indent=2))

    sys.exit(0 if findings else 1)


if __name__ == "__main__":
    cli()
