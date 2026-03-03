# Log Intelligence CLI

Turn raw, unstructured log lines into clean, structured JSON — powered by Claude.

---

## What it does

Log files are noisy. This CLI sends raw log lines to the Anthropic API and returns structured, validated JSON — extracting timestamps, severity levels, services, error types, HTTP details, and more. No regex. No brittle parsers. Just describe the log and get structure back.

---

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python log_cli.py demo
```

---

## Commands

| Command | Description |
|---------|-------------|
| `parse "<log line>"` | Parse a single raw log line |
| `batch <file>` | Parse every line in a file |
| `batch <file> -o out.json` | Batch parse and save to JSON |
| `demo` | Run 5 built-in samples |
| `cost-report` | Show session token usage and cost |

---

## Example Output

```json
{
  "timestamp": "2024-01-15T10:23:45.123",
  "level": "ERROR",
  "service": "order-service",
  "message": "NullPointerException while processing order",
  "error_type": "java.lang.NullPointerException",
  "stack_trace": "at com.example.OrderService.processOrder(OrderService.java:142)"
}
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `LANGCHAIN_TRACING_V2` | No | Enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | No | LangSmith API key |
| `LANGCHAIN_PROJECT` | No | LangSmith project name |

---

## Cost

Runs on `claude-sonnet-4-6` — $3/M input tokens, $15/M output tokens. A 5-log demo run costs roughly $0.02. Use `cost-report` to track session spend.
