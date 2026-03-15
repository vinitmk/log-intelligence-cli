"""
Eval harness for Log Intelligence CLI.
Runs 10 ground-truth log entries through the API and scores the results.

Scoring dimensions (per entry):
  json_valid          — did the response parse as valid JSON?
  field_accuracy      — fraction of exact-match fields that are correct
  completeness        — fraction of expected non-null fields that are non-null in response
  level_correct       — did it get the log level right?
  metadata_extraction — fraction of expected extra-field keys captured (N/A if none expected)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from rich.console import Console
from rich.table import Table

# Defer import of call_api at function level to avoid circular imports.
console = Console()

# ---------------------------------------------------------------------------
# Ground-truth dataset — 10 entries
# ---------------------------------------------------------------------------

GROUND_TRUTH: list[dict] = [
    # 1. Java NPE (order-service)
    {
        "id": "java-npe",
        "raw": (
            "2024-01-15 10:23:45.123 ERROR [order-service] "
            "java.lang.NullPointerException: Cannot invoke method getId() on null object "
            "at com.example.OrderService.processOrder(OrderService.java:142)"
        ),
        "expected": {
            "level": "ERROR",
            "service": "order-service",
            "error_type": "java.lang.NullPointerException",
            "stack_trace": "at com.example.OrderService.processOrder(OrderService.java:142)",
            "http_method": None,
            "status_code": None,
            "extra": None,
        },
    },
    # 2. nginx access log (combined format)
    {
        "id": "nginx-access",
        "raw": (
            '192.168.1.50 - frank [10/Oct/2024:13:55:36 -0700] '
            '"GET /api/v1/users HTTP/1.1" 200 1234 0.042'
        ),
        "expected": {
            "level": "INFO",
            "http_method": "GET",
            "http_path": "/api/v1/users",
            "status_code": 200,
            "response_time_ms": 42.0,
            "host": "192.168.1.50",
            "extra": {"user": "frank"},   # must capture the user field
        },
    },
    # 3. Kafka consumer warning
    {
        "id": "kafka-warn",
        "raw": (
            "WARN  [kafka-consumer-thread-1] "
            "org.apache.kafka.clients.consumer.internals.ConsumerCoordinator - "
            "Auto offset commit failed for group payment-processors: "
            "Commit cannot be completed since the group has already rebalanced"
        ),
        "expected": {
            "level": "WARN",
            "service": "ConsumerCoordinator",
            "error_type": None,
            "http_method": None,
            "status_code": None,
            "extra": None,
        },
    },
    # 4. Go runtime panic (level must be inferred as FATAL)
    {
        "id": "go-panic",
        "raw": (
            "goroutine 1 [running]: main.processRequest(0xc0001a4000, 0x7f3b2c000000, 0x400) "
            "panic: runtime error: index out of range [5] with length 3"
        ),
        "expected": {
            "level": "FATAL",
            "error_type": "panic",
            "http_method": None,
            "status_code": None,
        },
    },
    # 5. Linux kernel OOM killer (level must be inferred as ERROR)
    {
        "id": "linux-oom",
        "raw": (
            "Jan 15 10:30:01 prod-server-01 kernel: "
            "Out of memory: Kill process 12847 (java) score 987 or sacrifice child"
        ),
        "expected": {
            "level": "ERROR",
            "service": "kernel",
            "host": "prod-server-01",
            "pid": 12847,
            "error_type": "OutOfMemory",
            "extra": {"oom_score": 987},
        },
    },
    # 6. Structured JSON log (auth-service)
    {
        "id": "json-log",
        "raw": (
            '{"timestamp":"2024-01-15T10:45:00Z","level":"error","service":"auth-service",'
            '"message":"Token validation failed","user_id":"u-8821",'
            '"error":"invalid signature","request_id":"req-abc123"}'
        ),
        "expected": {
            "level": "ERROR",
            "service": "auth-service",
            "error_type": "invalid signature",
            "http_method": None,
            "status_code": None,
            "extra": {"user_id": "u-8821", "request_id": "req-abc123"},
        },
    },
    # 7. Syslog nginx CRIT
    {
        "id": "syslog-nginx-crit",
        "raw": (
            "Jan 15 11:02:33 web-01 nginx[1337]: 2024/01/15 11:02:33 [crit] 1337#0: "
            "*42 connect() to unix:/var/run/php-fpm.sock failed "
            "(11: Resource temporarily unavailable) while connecting to upstream"
        ),
        "expected": {
            "level": "FATAL",   # crit → FATAL per rules
            "host": "web-01",
            "pid": 1337,
            "service": "nginx",
            "http_method": None,
            "status_code": None,
        },
    },
    # 8. Structured health-check log with extra fields
    {
        "id": "health-check",
        "raw": (
            "2024-01-15T12:00:00.000Z INFO  health-checker "
            "service=api-gateway status=healthy latency_ms=3.2 "
            "checks_passed=5 checks_failed=0"
        ),
        "expected": {
            "level": "INFO",
            "service": "health-checker",
            "http_method": None,
            "status_code": None,
            "extra": {
                "service_name": "api-gateway",   # key name may vary — test for presence
                "checks_passed": 5,
                "checks_failed": 0,
            },
        },
    },
    # 9. Multi-line Python traceback (already merged into one string)
    {
        "id": "python-traceback",
        "raw": (
            "2024-03-20 14:55:01,234 ERROR root - Unhandled exception in worker\n"
            "Traceback (most recent call last):\n"
            '  File "/app/worker.py", line 88, in run\n'
            "    result = process(payload)\n"
            '  File "/app/processor.py", line 42, in process\n'
            "    raise ValueError(f\"Invalid payload: {payload!r}\")\n"
            "ValueError: Invalid payload: None"
        ),
        "expected": {
            "level": "ERROR",
            "error_type": "ValueError",
            "stack_trace": 'File "/app/processor.py", line 42, in process',
            "http_method": None,
            "status_code": None,
        },
    },
    # 10. Docker/container log with request tracing
    {
        "id": "docker-request",
        "raw": (
            "2024-01-15T15:30:00.500Z ERROR api-gateway "
            'msg="upstream timeout" request_id=req-xyz999 '
            "method=POST path=/v1/checkout upstream=payment-service "
            "duration_ms=30001 status=504"
        ),
        "expected": {
            "level": "ERROR",
            "service": "api-gateway",
            "http_method": "POST",
            "http_path": "/v1/checkout",
            "status_code": 504,
            "response_time_ms": 30001.0,
            "extra": {"request_id": "req-xyz999", "upstream": "payment-service"},
        },
    },
]


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

# Fields where we require exact equality.
_EXACT_FIELDS = ["level", "http_method", "http_path", "status_code", "pid"]


def score_response(parsed_dict: dict, expected: dict) -> dict:
    """Score one API response against expected values.

    Returns a dict with keys:
      json_valid, field_accuracy, completeness, level_correct, metadata_extraction
    """
    # --- field accuracy ---------------------------------------------------
    checkable = {f: expected[f] for f in _EXACT_FIELDS if f in expected and expected[f] is not None}
    if checkable:
        correct = sum(1 for f, v in checkable.items() if parsed_dict.get(f) == v)
        field_accuracy = correct / len(checkable)
    else:
        field_accuracy = 1.0  # nothing to check

    # --- completeness (non-null expected fields present in response) -------
    non_null = {k: v for k, v in expected.items() if v is not None and k != "extra"}
    if non_null:
        captured = sum(1 for k in non_null if parsed_dict.get(k) is not None)
        completeness = captured / len(non_null)
    else:
        completeness = 1.0

    # --- level correctness ------------------------------------------------
    level_correct = parsed_dict.get("level") == expected.get("level")

    # --- metadata extraction (extra fields) --------------------------------
    expected_extra = expected.get("extra")
    if expected_extra:
        parsed_extra = parsed_dict.get("extra") or {}
        # Check keys (values may differ in name/type slightly)
        found = sum(1 for k in expected_extra if k in parsed_extra)
        metadata_extraction: Optional[float] = found / len(expected_extra)
    else:
        metadata_extraction = None  # N/A

    return {
        "json_valid": True,
        "field_accuracy": round(field_accuracy, 3),
        "completeness": round(completeness, 3),
        "level_correct": level_correct,
        "metadata_extraction": round(metadata_extraction, 3) if metadata_extraction is not None else None,
    }


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _meta_str(v: Optional[float]) -> str:
    return "N/A" if v is None else _pct(v)


# ---------------------------------------------------------------------------
# Main eval runner
# ---------------------------------------------------------------------------

def run_eval(client: anthropic.Anthropic, output_path: Path = Path("eval_results.json")) -> None:
    from log_cli import call_api  # local import keeps startup fast

    all_results: list[dict] = []
    row_data: list[tuple] = []

    console.print(f"\n[bold]Running eval harness — {len(GROUND_TRUTH)} entries…[/bold]\n")

    for entry in GROUND_TRUTH:
        eid   = entry["id"]
        raw   = entry["raw"]
        expected = entry["expected"]

        console.print(f"  [cyan]{eid}[/cyan] …", end=" ")

        try:
            parsed, usage = call_api(raw, client)
            parsed_dict = parsed.model_dump()
            scores = score_response(parsed_dict, expected)
            scores["json_valid"] = True
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]FAILED[/red] ({exc.__class__.__name__})")
            scores = {
                "json_valid": False,
                "field_accuracy": 0.0,
                "completeness": 0.0,
                "level_correct": False,
                "metadata_extraction": None,
            }
            parsed_dict = {}
            usage = {}

        console.print(
            f"[green]OK[/green]  "
            f"acc={_pct(scores['field_accuracy'])} "
            f"cmp={_pct(scores['completeness'])} "
            f"lvl={'✓' if scores['level_correct'] else '✗'} "
            f"meta={_meta_str(scores['metadata_extraction'])}"
        )

        row_data.append((eid, scores))
        all_results.append({
            "id": eid,
            "raw": raw,
            "expected": expected,
            "parsed": parsed_dict,
            "scores": scores,
            "usage": usage,
        })

    # --- aggregate scores -------------------------------------------------
    n = len(all_results)
    avg_fa   = sum(r["scores"]["field_accuracy"]  for r in all_results) / n
    avg_cmp  = sum(r["scores"]["completeness"]    for r in all_results) / n
    pct_lv   = sum(1 for r in all_results if r["scores"]["level_correct"]) / n
    meta_rows = [r["scores"]["metadata_extraction"] for r in all_results
                 if r["scores"]["metadata_extraction"] is not None]
    avg_meta = sum(meta_rows) / len(meta_rows) if meta_rows else None
    pct_json = sum(1 for r in all_results if r["scores"]["json_valid"]) / n

    # --- Rich table -------------------------------------------------------
    table = Table(title="Eval Score Report", border_style="green", show_lines=True)
    table.add_column("ID",             style="bold cyan",   no_wrap=True)
    table.add_column("JSON?",          justify="center")
    table.add_column("Field Acc",      justify="right")
    table.add_column("Complete",       justify="right")
    table.add_column("Level ✓",        justify="center")
    table.add_column("Meta Extr",      justify="right")

    for eid, s in row_data:
        table.add_row(
            eid,
            "[green]✓[/green]" if s["json_valid"] else "[red]✗[/red]",
            _pct(s["field_accuracy"]),
            _pct(s["completeness"]),
            "[green]✓[/green]" if s["level_correct"] else "[red]✗[/red]",
            _meta_str(s["metadata_extraction"]),
        )

    # Summary row
    table.add_section()
    table.add_row(
        "[bold]AVERAGE[/bold]",
        _pct(pct_json),
        _pct(avg_fa),
        _pct(avg_cmp),
        _pct(pct_lv),
        _meta_str(avg_meta),
        style="bold",
    )

    console.print()
    console.print(table)

    # --- save to JSON -------------------------------------------------------
    output: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": "claude-sonnet-4-6",
        "n_entries": n,
        "aggregate": {
            "json_valid_pct":        round(pct_json,  3),
            "avg_field_accuracy":    round(avg_fa,    3),
            "avg_completeness":      round(avg_cmp,   3),
            "level_correct_pct":     round(pct_lv,    3),
            "avg_metadata_extraction": round(avg_meta, 3) if avg_meta is not None else None,
        },
        "entries": all_results,
    }
    output_path.write_text(json.dumps(output, indent=2, default=str))
    console.print(f"\n[green]Results saved to {output_path}[/green]")


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    run_eval(client)
