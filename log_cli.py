"""
Log Intelligence CLI — Phase 1
Parses raw log lines into structured JSON using the Anthropic API.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import anthropic
import click
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Pydantic schema for structured log output
# ---------------------------------------------------------------------------

class ParsedLog(BaseModel):
    timestamp: Optional[str] = None
    level: Optional[str] = None          # INFO, WARN, ERROR, DEBUG, FATAL, etc.
    service: Optional[str] = None        # app / service name
    message: str                         # human-readable summary
    error_type: Optional[str] = None     # exception class or error code
    stack_trace: Optional[str] = None    # first line of stack trace if present
    http_method: Optional[str] = None    # GET, POST, etc.
    http_path: Optional[str] = None
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    host: Optional[str] = None
    pid: Optional[int] = None
    extra: Optional[dict] = None         # catch-all for additional fields

    @field_validator("level")
    @classmethod
    def normalise_level(cls, v):
        if v is not None:
            return v.upper()
        return v

    @field_validator("status_code")
    @classmethod
    def valid_status_code(cls, v):
        if v is not None and not (100 <= v <= 599):
            raise ValueError(f"Invalid HTTP status code: {v}")
        return v


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

COST_PER_MILLION_INPUT  = 3.00   # USD — claude-sonnet-4-6
COST_PER_MILLION_OUTPUT = 15.00

_session_input_tokens  = 0
_session_output_tokens = 0
_session_calls         = 0


def record_usage(input_tokens: int, output_tokens: int) -> dict:
    global _session_input_tokens, _session_output_tokens, _session_calls
    _session_input_tokens  += input_tokens
    _session_output_tokens += output_tokens
    _session_calls         += 1

    call_cost = (
        input_tokens  / 1_000_000 * COST_PER_MILLION_INPUT +
        output_tokens / 1_000_000 * COST_PER_MILLION_OUTPUT
    )
    return {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cost_usd":      round(call_cost, 6),
    }


def session_cost_usd() -> float:
    return round(
        _session_input_tokens  / 1_000_000 * COST_PER_MILLION_INPUT +
        _session_output_tokens / 1_000_000 * COST_PER_MILLION_OUTPUT,
        6,
    )


# ---------------------------------------------------------------------------
# Core parse logic
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a log analysis expert. Parse the raw log line provided by the user and extract structured fields into a JSON object.

## Output Schema

{
  "timestamp":        "<ISO-8601 or original timestamp string, or null>",
  "level":            "<log level string or null>",
  "service":          "<app/service name or null>",
  "message":          "<concise human-readable summary of what happened>",
  "error_type":       "<exception class or error code or null>",
  "stack_trace":      "<first line of stack trace or null>",
  "http_method":      "<HTTP verb or null>",
  "http_path":        "<request path or null>",
  "status_code":      <integer HTTP status or null>,
  "response_time_ms": <float milliseconds or null>,
  "host":             "<hostname/IP or null>",
  "pid":              <integer PID or null>,
  "extra":            {<any remaining key-value pairs not captured above, or null>}
}

## Rules

1. Do not include any explanation, markdown formatting, or code fences. Return ONLY the raw JSON object.
2. Never omit fields — use null for any field not present in the log.
3. Normalise level to uppercase: INFO, WARN, ERROR, DEBUG, FATAL, TRACE.
4. Never hallucinate fields. If data is not explicitly present in the log, set the field to null.
5. Multi-line logs: treat the entire input as one log entry and combine into a single JSON object.
6. Timestamps: if the format is unambiguous (e.g. ISO-8601, RFC 3164), convert to ISO-8601. If ambiguous or non-standard, preserve the original timestamp string exactly.
7. Infer log level when not explicitly stated:
   - "panic", "fatal", "emerg", "crit" → FATAL
   - "OOM", "Out of memory", "kill process" → ERROR
   - "warn", "warning" → WARN
   - "debug", "trace" → DEBUG
   - Default to INFO when a severity indicator is absent.
8. If extra key-value pairs exist that are not captured by the schema fields, collect them in the extra object. Otherwise set extra to null.

## Few-Shot Examples

### Example 1 — Java exception with stack trace

Input:
2024-03-12 08:14:22.456 ERROR [payment-service] java.lang.NullPointerException: Cannot invoke method getAmount() on null object
\tat com.example.PaymentService.processPayment(PaymentService.java:87)
\tat com.example.PaymentController.handleRequest(PaymentController.java:34)

Output:
{"timestamp":"2024-03-12T08:14:22.456","level":"ERROR","service":"payment-service","message":"NullPointerException while invoking getAmount() on null object in PaymentService.processPayment","error_type":"java.lang.NullPointerException","stack_trace":"at com.example.PaymentService.processPayment(PaymentService.java:87)","http_method":null,"http_path":null,"status_code":null,"response_time_ms":null,"host":null,"pid":null,"extra":null}

### Example 2 — nginx / Apache access log

Input:
203.0.113.42 - alice [12/Mar/2024:08:15:01 +0000] "POST /api/v2/orders HTTP/1.1" 201 876 0.053

Output:
{"timestamp":"2024-03-12T08:15:01+00:00","level":"INFO","service":null,"message":"HTTP POST /api/v2/orders responded 201 in 53ms","error_type":null,"stack_trace":null,"http_method":"POST","http_path":"/api/v2/orders","status_code":201,"response_time_ms":53.0,"host":"203.0.113.42","pid":null,"extra":{"user":"alice","response_bytes":876,"protocol":"HTTP/1.1"}}

### Example 3 — syslog kernel message

Input:
Mar 12 08:20:45 prod-db-02 kernel: Out of memory: Kill process 31412 (postgres) score 902 or sacrifice child

Output:
{"timestamp":"2024-03-12T08:20:45","level":"ERROR","service":"kernel","message":"OOM killer terminated process postgres (PID 31412) with score 902","error_type":"OutOfMemory","stack_trace":null,"http_method":null,"http_path":null,"status_code":null,"response_time_ms":null,"host":"prod-db-02","pid":31412,"extra":{"oom_score":902,"oom_action":"kill"}}
"""


def call_api(raw_log: str, client: anthropic.Anthropic, attempt: int = 0) -> tuple[ParsedLog, dict]:
    """Call the Anthropic API and return a validated ParsedLog + usage dict.
    Retries up to 3 times with error feedback on JSON/validation failures.
    """
    messages = [{"role": "user", "content": raw_log}]

    last_error: Optional[str] = None
    for retry in range(3):
        if retry > 0:
            feedback = (
                f"Your previous response produced invalid output: {last_error}\n"
                f"Try again. Return ONLY valid JSON matching the schema."
            )
            messages = [
                {"role": "user",      "content": raw_log},
                {"role": "assistant", "content": "<invalid previous response>"},
                {"role": "user",      "content": feedback},
            ]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        raw_text = response.content[0].text.strip()
        usage    = record_usage(response.usage.input_tokens, response.usage.output_tokens)

        # Strip possible markdown fences
        if raw_text.startswith("```"):
            raw_text = "\n".join(raw_text.split("\n")[1:])
            raw_text = raw_text.rsplit("```", 1)[0].strip()

        try:
            data   = json.loads(raw_text)
            parsed = ParsedLog(**data)
            return parsed, usage
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last_error = str(exc)
            console.print(f"  [yellow]Retry {retry + 1}/3 — {exc.__class__.__name__}: {exc}[/yellow]")

    raise RuntimeError(f"Failed to get valid JSON after 3 retries. Last error: {last_error}")


def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY not set. Copy .env.example → .env and add your key.")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def render_result(raw_log: str, parsed: ParsedLog, usage: dict) -> None:
    console.print(Panel(f"[dim]{raw_log}[/dim]", title="Raw Log", border_style="blue"))
    json_str = parsed.model_dump_json(indent=2, exclude_none=True)
    console.print(Syntax(json_str, "json", theme="monokai", line_numbers=False))
    console.print(
        f"[dim]Tokens: {usage['input_tokens']} in / {usage['output_tokens']} out  "
        f"| Cost: ${usage['cost_usd']:.6f}[/dim]\n"
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Log Intelligence CLI — parse raw logs into structured JSON with AI."""


@cli.command()
@click.argument("log_line")
def parse(log_line: str):
    """Parse a single LOG_LINE into structured JSON."""
    client = get_client()
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Parsing log…", total=None)
        parsed, usage = call_api(log_line, client)
    render_result(log_line, parsed, usage)


@cli.command()
@click.argument("file", type=click.Path(exists=True, readable=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Write all parsed results to this JSON file.")
def batch(file: Path, output: Optional[Path]):
    """Parse every line in FILE into structured JSON."""
    client  = get_client()
    lines   = [l.strip() for l in file.read_text().splitlines() if l.strip() and not l.startswith("#")]
    results = []

    console.print(f"[bold]Batch parsing [cyan]{len(lines)}[/cyan] log lines from [cyan]{file}[/cyan]…[/bold]\n")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Parsing…", total=len(lines))
        for i, line in enumerate(lines, 1):
            progress.update(task, description=f"Line {i}/{len(lines)}…")
            try:
                parsed, usage = call_api(line, client)
                results.append({"raw": line, "parsed": parsed.model_dump(exclude_none=True), "usage": usage})
                progress.advance(task)
            except RuntimeError as exc:
                console.print(f"[red]Line {i} failed:[/red] {exc}")
                results.append({"raw": line, "error": str(exc)})
                progress.advance(task)

    console.print(f"\n[green]Done.[/green] Parsed {len(results)} lines.\n")

    for r in results:
        if "parsed" in r:
            render_result(r["raw"], ParsedLog(**r["parsed"]), r["usage"])
        else:
            console.print(f"[red]Failed:[/red] {r['raw']}\n  {r['error']}\n")

    if output:
        output.write_text(json.dumps(results, indent=2))
        console.print(f"[green]Results written to {output}[/green]")


@cli.command()
def demo():
    """Parse 5 built-in sample log lines to demonstrate the CLI."""
    samples = [
        '2024-01-15 10:23:45.123 ERROR [order-service] java.lang.NullPointerException: Cannot invoke method getId() on null object at com.example.OrderService.processOrder(OrderService.java:142)',
        '192.168.1.50 - frank [10/Oct/2024:13:55:36 -0700] "GET /api/v1/users HTTP/1.1" 200 1234 0.042',
        'WARN  [kafka-consumer-thread-1] org.apache.kafka.clients.consumer.internals.ConsumerCoordinator - Auto offset commit failed for group payment-processors: Commit cannot be completed since the group has already rebalanced',
        'goroutine 1 [running]: main.processRequest(0xc0001a4000, 0x7f3b2c000000, 0x400) panic: runtime error: index out of range [5] with length 3',
        'Jan 15 10:30:01 prod-server-01 kernel: Out of memory: Kill process 12847 (java) score 987 or sacrifice child',
    ]

    client = get_client()
    console.print(Panel("[bold]Log Intelligence CLI — Demo[/bold]\nParsing 5 sample log lines…", border_style="green"))

    for i, line in enumerate(samples, 1):
        console.print(f"\n[bold cyan]── Sample {i}/5 ──[/bold cyan]")
        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
                p.add_task("Calling API…", total=None)
                parsed, usage = call_api(line, client)
            render_result(line, parsed, usage)
        except RuntimeError as exc:
            console.print(f"[red]Failed:[/red] {exc}\n")

    _print_session_cost()


@cli.command("cost-report")
def cost_report():
    """Show token usage and estimated cost for this session."""
    _print_session_cost()


def _print_session_cost():
    table = Table(title="Session Cost Report", border_style="green")
    table.add_column("Metric",       style="bold")
    table.add_column("Value",        justify="right")
    table.add_row("API calls",       str(_session_calls))
    table.add_row("Input tokens",    f"{_session_input_tokens:,}")
    table.add_row("Output tokens",   f"{_session_output_tokens:,}")
    table.add_row("Total tokens",    f"{_session_input_tokens + _session_output_tokens:,}")
    table.add_row("Estimated cost",  f"${session_cost_usd():.6f}")
    console.print(table)


if __name__ == "__main__":
    cli()
