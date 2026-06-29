# CLAUDE.md — Data Governance / DQ Framework

## Project Summary

Banking-grade **Shift-Left Data Quality Framework** built on Great Expectations 1.x.
Three zones of defense: Ingestion → Processing → Reporting.
All DQ rules are declared in YAML — no Python changes needed to add or modify checks.

**GitHub:** https://github.com/karankedu/data-governance  
**Stack:** Python 3.11, Great Expectations 1.18.x, Pydantic v2, PyYAML, pandas 3.x  
**Package manager:** `uv` — always use `uv add`, never `pip install`

---

## How to Run

```bash
# Install dependencies
uv sync

# Run both demo scenarios
uv run python main.py

# Run one scenario
uv run python main.py --scenario a
uv run python main.py --scenario b

# Debug mode
uv run python main.py --log-level DEBUG
```

---

## Architecture

```
main.py  (CLI: argparse)
  └── DQPipeline.from_config("config/pipeline.yaml", "config/rules/")
        ├── Zone 1: ingestion_suite   → config/rules/ingestion.yaml
        ├── Zone 2: processing_suite  → config/rules/processing.yaml
        └── Zone 3: reporting_suite   → config/rules/reporting.yaml
```

**DQEngine** (`dq_framework/engine.py`) — reads `ZoneConfig` (Pydantic), maps
`"expect_column_values_to_not_be_null"` → `gx.expectations.ExpectColumnValuesToNotBeNull`
via snake_case → PascalCase conversion. No hardcoded expectation wiring.

**Circuit breaker** — fires in Zone 1 only. CRITICAL failures raise
`CircuitBreakerTripped` *after* records are added to `all_records`, so the
partial audit trail is always written.

---

## Key Files

| File | Role |
|------|------|
| `dq_framework/config.py` | Pydantic models (`RuleConfig`, `ZoneConfig`, `PipelineConfig`) + YAML loaders |
| `dq_framework/engine.py` | `DQEngine.build_suite()` — generic suite builder; `run_checkpoint()` — static GX runner |
| `dq_framework/reporting.py` | `AuditRecord` dataclass, `parse_results()`, console formatter, JSON audit writer |
| `dq_framework/data.py` | Deterministic mock data (`scenario_a`, `scenario_b`) seeded with `random.Random(42)` |
| `dq_framework/pipeline.py` | `DQPipeline` class — orchestrates zones, manages `all_records`, writes audit log |
| `config/pipeline.yaml` | Ledger total, tolerance %, date bounds, row count thresholds |
| `config/rules/*.yaml` | One file per zone; each rule has `id`, `expectation`, `params`/`param_refs`/`runtime_params`, `dimension`, `criticality` |
| `main.py` | CLI entry point — argparse, logging setup, calls `DQPipeline.from_config()` |
| `shift_left_dq_framework.py` | Original self-contained single-script demo (kept for reference) |

---

## Rule Config Schema

```yaml
- id: ING-003                                    # unique rule ID
  description: "PAN must never be null"
  column: PAN                                    # omit for table-level expectations
  expectation: expect_column_values_to_not_be_null
  params: {}                                     # static kwargs passed directly to GX
  param_refs:                                    # resolved from DataConfig properties at build time
    min_value: operational_date_min_dt           # → datetime.datetime object
    max_value: expected_ledger_min               # → float
  runtime_params:                                # injected by pipeline.run() at call time
    - value_set                                  # e.g. customer IDs from master table
  dimension: Completeness                        # one of 6 DQ dimensions
  criticality: CRITICAL                          # CRITICAL (halts) | WARNING (logs, continues)
```

**Three param sources — resolved in this order:**
1. `params` — static YAML values
2. `param_refs` — DataConfig property names (computed from `pipeline.yaml` settings)
3. `runtime_params` — injected at `pipeline.run()` time (e.g. `value_set` for FK checks)

---

## DataConfig Computed Properties

These are the valid values for `param_refs` keys:

| Property | Type | Derived from |
|----------|------|--------------|
| `expected_ledger_min` | `float` | `expected_ledger_total * (1 - ledger_tolerance_pct)` |
| `expected_ledger_max` | `float` | `expected_ledger_total * (1 + ledger_tolerance_pct)` |
| `operational_date_min_dt` | `datetime.datetime` | Parsed from `operational_date_min` string |
| `operational_date_max_dt` | `datetime.datetime` | Parsed from `operational_date_max` string, set to 23:59:59 |
| `historical_min_rows` | `int` | Direct from config |
| `historical_max_rows` | `int` | Direct from config |

---

## Critical GX 1.x Gotchas

1. **DateTime bounds must be `datetime.datetime`, not `datetime.date` or strings.**  
   GX 1.18 parses ISO date strings into `datetime.date` objects, which cannot be
   compared against pandas `Timestamp` (datetime64) columns — the result dict is
   empty `{}` and the check silently fails. Always use `datetime.datetime` instances.

2. **tqdm progress bars go to stderr.** Suppressed via `contextlib.redirect_stderr()`
   in `DQEngine.run_checkpoint()`. Setting `TQDM_DISABLE=1` env var alone is unreliable
   because GX passes `disable=False` explicitly to tqdm instances.

3. **Column is in `kwargs`, not as an attribute.** Access via
   `exp_result.expectation_config.kwargs.get("column", "TABLE")` — there is no
   `.column` attribute on `ExpectationConfiguration` in GX 1.x.

4. **`ExpectTableRowCountToBeBetween` has no `column` kwarg.** Use `"TABLE"` as the
   sentinel in registry lookups: `kwargs.get("column", "TABLE")`.

5. **Fresh ephemeral context per `pipeline.run()` call** — avoids name-collision errors
   when running multiple scenarios back-to-back in the same process.

---

## Audit Output

- **Console:** emoji-formatted zone-by-zone output + audit trail table
- **JSON log:** `logs/audit/audit_<scenario>_<timestamp>.json`  
  Contains `schema_version`, `summary` (pass/fail/critical counts), and per-rule `records`
- **Pipeline log:** `logs/dq_pipeline.log` — Python logging output for monitoring

---

## Adding a New DQ Rule (no Python needed)

Edit the relevant `config/rules/<zone>.yaml`:

```yaml
- id: ING-005
  description: "Account type must be SAVINGS or CURRENT"
  column: Account_Type
  expectation: expect_column_values_to_be_in_set
  params:
    value_set: ["SAVINGS", "CURRENT"]
  dimension: Validity
  criticality: WARNING
```

Any GX 1.x expectation listed under `gx.expectations.*` is supported.
Use the snake_case name: `ExpectColumnValuesToMatchRegex` → `expect_column_values_to_match_regex`.

---

## Commit Style

- No `Co-Authored-By: Claude` trailers
- No AI tool references in commit messages
- Technical, product-focused commit subjects only
