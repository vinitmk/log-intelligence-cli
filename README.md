# Log Intelligence CLI

> **60-Day AI Engineering Roadmap — Phase 1 (Days 1–10)**
> Parse raw log lines into structured JSON using the Anthropic API, Pydantic validation, and LangSmith tracing.

---

## Quick Start

```bash
# 1. Create & activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY (required) and LANGCHAIN_API_KEY (optional)

# 4. Run the demo
python log_cli.py demo
```

---

## Project Structure

```
log-intelligence-cli/
├── log_cli.py          # Main CLI (Click + Pydantic + Rich)
├── requirements.txt    # Python dependencies
├── sample_logs.txt     # 8 diverse log samples for testing
├── .env.example        # Environment variable template
├── .gitignore
├── README.md
└── PHASE1_PLAN.md      # Day-by-day plan for Days 1–10
```

---

## Available Commands

| Command | Description |
|---------|-------------|
| `python log_cli.py parse "<log line>"` | Parse a single raw log line |
| `python log_cli.py batch sample_logs.txt` | Parse every line in a file |
| `python log_cli.py batch sample_logs.txt -o results.json` | Batch parse + save output |
| `python log_cli.py demo` | Parse 5 built-in sample logs |
| `python log_cli.py cost-report` | Show session token usage & cost |

---

## Example Output

```json
{
  "timestamp": "2024-01-15T10:23:45.123",
  "level": "ERROR",
  "service": "order-service",
  "message": "NullPointerException while processing order — getId() called on null",
  "error_type": "java.lang.NullPointerException",
  "stack_trace": "at com.example.OrderService.processOrder(OrderService.java:142)"
}
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | **Yes** | Your Anthropic API key |
| `LANGCHAIN_TRACING_V2` | No | Enable LangSmith tracing (`true`/`false`) |
| `LANGCHAIN_API_KEY` | No | LangSmith API key |
| `LANGCHAIN_PROJECT` | No | LangSmith project name |

---

## Cost Model

Pricing based on `claude-sonnet-4-6`:
- Input:  $3.00 / 1M tokens
- Output: $15.00 / 1M tokens

Run `python log_cli.py cost-report` at any time to see session totals.
