# Phase 1 Plan — Log Intelligence CLI (Days 1–10)

> Goal: Build a production-quality CLI that converts raw log lines → structured JSON using the Anthropic API.

---

## Day 1 — Project Scaffold ✅
- [x] Project structure, `log_cli.py`, `requirements.txt`, `.env.example`
- [x] Pydantic `ParsedLog` schema covering timestamp, level, service, error_type, http fields, host, pid, extra
- [x] Retry logic (up to 3 attempts) with error feedback injected into the conversation
- [x] Per-call cost tracking (input/output tokens → USD)
- [x] `parse`, `batch`, `demo`, `cost-report` Click commands
- [x] Rich terminal output (panels, syntax highlighting, progress spinners)
- [x] `sample_logs.txt` with 8 diverse formats, git repo initialised

---

## Day 2 — Prompt Engineering & Schema Hardening
- [ ] Experiment with few-shot examples in the system prompt
- [ ] Test adversarial log lines (multiline, binary garbage, mixed languages)
- [ ] Add `confidence` field to `ParsedLog` (0.0–1.0) based on how many fields were extracted
- [ ] Evaluate: measure field-extraction hit rate across all 8 sample logs
- [ ] Commit: `Day 2: Few-shot prompting + confidence score`

---

## Day 3 — Structured Outputs (JSON Mode)
- [ ] Switch to Anthropic's **tool use** / `response_format` to enforce schema at the API level
- [ ] Compare reliability vs. plain text → JSON parsing approach from Day 1
- [ ] Document accuracy delta and latency trade-off
- [ ] Commit: `Day 3: Tool-use structured outputs`

---

## Day 4 — LangSmith Tracing Integration
- [ ] Wrap `call_api` with a LangSmith `RunTree` or `traceable` decorator
- [ ] Log: raw input, model response, token counts, latency, retry count
- [ ] Create a LangSmith dataset from `sample_logs.txt` for future evals
- [ ] Verify traces appear in the LangSmith dashboard
- [ ] Commit: `Day 4: LangSmith tracing`

---

## Day 5 — Advanced Cost Tracking & Rate Limiting
- [ ] Persist cost log to `costs.jsonl` (one entry per API call)
- [ ] Add `--dry-run` flag to `batch` that estimates cost before calling the API
- [ ] Implement token-bucket rate limiter to stay within API rate limits
- [ ] Commit: `Day 5: Persistent cost log + rate limiter`

---

## Day 6 — Eval Harness Design
- [ ] Define eval dimensions: field extraction accuracy, JSON validity rate, latency p50/p95
- [ ] Write `eval.py` with a golden dataset of 20 logs + expected parsed fields
- [ ] Automated scorer: exact-match for discrete fields, fuzzy-match for message strings
- [ ] Commit: `Day 6: Eval harness skeleton`

---

## Day 7 — Multi-Model Comparison
- [ ] Add `--model` flag to `parse` and `batch` commands
- [ ] Test `claude-haiku-4-5` vs `claude-sonnet-4-6` on the eval dataset
- [ ] Record: accuracy, latency, cost per model
- [ ] Commit: `Day 7: Multi-model benchmarking`

---

## Day 8 — Streaming & UX Polish
- [ ] Stream tokens with `client.messages.stream()` for large log batches
- [ ] Show live token-by-token output in `parse` command
- [ ] Add `--format` flag: `json` (raw), `table`, `pretty` (default)
- [ ] Commit: `Day 8: Streaming + output formats`

---

## Day 9 — Error Classification & Alerting
- [ ] Extend `ParsedLog` with `severity_score` (1–10) and `alert` (bool)
- [ ] Add alerting rules (e.g., OOM → critical, 5xx → warning)
- [ ] Write `classify.py` to batch-classify a log file and emit a summary report
- [ ] Commit: `Day 9: Severity scoring + alert classifier`

---

## Day 10 — Phase 1 Review & Documentation
- [ ] Run full eval harness; record final accuracy numbers
- [ ] Profile bottlenecks; optimise prompt if needed
- [ ] Write `RETROSPECTIVE.md`: what worked, what didn't, cost breakdown
- [ ] Tag release `v0.1.0`
- [ ] Commit: `Day 10: Phase 1 complete — eval results + retrospective`

---

## Key Metrics to Track Throughout Phase 1

| Metric | Target |
|--------|--------|
| JSON validity rate | ≥ 95% on first attempt |
| Field extraction hit rate | ≥ 80% across 20-log eval set |
| Average latency | < 3 s per log line |
| Cost per 1,000 logs | < $0.50 |
| Retry rate | < 10% |
