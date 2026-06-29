# Shift-Left Data Quality Framework

> A production-ready, configuration-driven Data Quality (DQ) framework built on **Great Expectations 1.x**, demonstrating a banking-grade **Three Zones of Defense** architecture across all six core DQ dimensions.

---

## Overview

Traditional data quality checks run at the end of a pipeline — by then, bad data has already poisoned downstream systems, reports, and regulatory submissions. **Shift-Left DQ** moves validation as close to the data source as possible, catching defects before they propagate.

This framework implements that principle through three sequential validation zones, each acting as a gate:

```
Raw Data ──► [ ZONE 1: Ingestion ] ──► [ ZONE 2: Processing ] ──► [ ZONE 3: Reporting ]
                Circuit Breaker            Transform & Enrich         Aggregate Analytics
                (CRITICAL rules)           (Uniqueness / FK)          (Reconciliation)
```

If a **CRITICAL** expectation fails at any zone, the **circuit breaker** fires — halting the pipeline and preventing corrupt data from advancing downstream.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DQ Pipeline Orchestrator                        │
│                      dq_framework/pipeline.py                       │
├──────────────────┬──────────────────────┬───────────────────────────┤
│   ZONE 1         │   ZONE 2             │   ZONE 3                  │
│   Ingestion      │   Processing         │   Reporting               │
│                  │                      │                           │
│  • Timeliness    │  • Uniqueness        │  • Accuracy (Recon)       │
│  • Validity      │  • Consistency (FK)  │  • Anomaly Detection      │
│  • Completeness  │                      │                           │
│  ⚡ Circuit       │                      │                           │
│    Breaker       │                      │                           │
├──────────────────┴──────────────────────┴───────────────────────────┤
│                        DQ Engine                                    │
│               dq_framework/engine.py                                │
│   Reads YAML rules → resolves params → builds GX suites             │
├─────────────────────────────────────────────────────────────────────┤
│                     Rule Configuration (YAML)                       │
│   config/rules/ingestion.yaml                                       │
│   config/rules/processing.yaml                                      │
│   config/rules/reporting.yaml                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Principle: Configuration Over Code

**Adding a new DQ rule requires zero Python changes.** Rules are declared in YAML and the engine resolves them to Great Expectations classes at runtime:

```yaml
# config/rules/ingestion.yaml
- id: ING-005
  description: "Transaction type must be CREDIT or DEBIT"
  column: Transaction_Type
  expectation: expect_column_values_to_be_in_set
  params:
    value_set: ["CREDIT", "DEBIT"]
  dimension: Validity
  criticality: WARNING
```

---

## Features

| Feature | Detail |
|---|---|
| **Config-driven rules** | All DQ checks declared in YAML — no hardcoded logic |
| **Pydantic validation** | Config schema is validated at startup; bad configs fail fast |
| **Circuit breaker** | CRITICAL failures at Zone 1 halt the pipeline immediately |
| **6 DQ dimensions** | Timeliness, Validity, Completeness, Uniqueness, Consistency, Accuracy |
| **Anomaly detection** | Volume thresholds catch unexpected row-count deviations |
| **Structured audit logs** | Every run writes a timestamped JSON audit log to `logs/audit/` |
| **Python logging** | INFO/DEBUG/ERROR levels; logs written to `logs/dq_pipeline.log` |
| **CLI interface** | `--scenario`, `--log-level`, `--rules-dir`, `--pipeline-config` flags |
| **Ephemeral GX context** | No filesystem side-effects; safe to run in CI/CD pipelines |

---

## Tech Stack

| Component | Version |
|---|---|
| Python | 3.11 |
| Great Expectations | 1.18.x |
| Pydantic | 2.x |
| pandas | 3.x |
| PyYAML | 6.x |
| uv (package manager) | 0.11.x |

---

## Project Structure

```
data-governance/
├── config/
│   ├── pipeline.yaml              # Pipeline-level settings & thresholds
│   └── rules/
│       ├── ingestion.yaml         # Zone 1: Timeliness, Validity, Completeness
│       ├── processing.yaml        # Zone 2: Uniqueness, Consistency
│       └── reporting.yaml         # Zone 3: Accuracy, Anomaly Detection
│
├── dq_framework/
│   ├── __init__.py
│   ├── config.py                  # Pydantic models + YAML loaders
│   ├── engine.py                  # Generic GX suite builder from rule configs
│   ├── reporting.py               # AuditRecord, console formatter, JSON writer
│   ├── data.py                    # Mock data generators (banking scenarios)
│   └── pipeline.py                # Orchestrator + CircuitBreakerTripped
│
├── main.py                        # CLI entry point
├── shift_left_dq_framework.py     # Self-contained single-script demo
├── pyproject.toml                 # Project metadata & dependencies (uv)
└── uv.lock                        # Pinned dependency lockfile
```

---

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — fast Python package manager
- Python 3.11 (managed automatically by uv)

### Installation

```bash
# Clone the repository
git clone https://github.com/karankedu/data-governance.git
cd data-governance

# Create virtual environment and install dependencies
uv sync
```

---

## Usage

### Run Both Demo Scenarios

```bash
uv run python main.py
```

### Run a Specific Scenario

```bash
# Scenario A — healthy dataset (all checks pass)
uv run python main.py --scenario a

# Scenario B — corrupted dataset (circuit breaker fires)
uv run python main.py --scenario b
```

### Verbose Debug Output

```bash
uv run python main.py --log-level DEBUG
```

### Custom Config Paths

```bash
uv run python main.py \
  --pipeline-config config/pipeline.yaml \
  --rules-dir config/rules
```

### CLI Reference

```
usage: dq-framework [-h] [--scenario {a,b,both}] [--pipeline-config PATH]
                    [--rules-dir DIR] [--log-level {DEBUG,INFO,WARNING,ERROR}]

options:
  --scenario        Scenario to run (default: both)
  --pipeline-config Path to pipeline.yaml (default: config/pipeline.yaml)
  --rules-dir       Directory containing zone rule YAML files
  --log-level       Logging verbosity (default: INFO)
```

---

## Demo Scenarios

### Scenario A — Healthy Dataset

All 8 rules pass across all three zones. The pipeline completes successfully.

```
  🏦  BANKING_DQ_PIPELINE  —  Scenario-A_Healthy-Dataset
  ──────────────────────────────────────────────────────
  ZONE 1 — Ingestion  (Circuit Breaker Active)
  ✅  [WARNING ]  Timeliness            Transaction_Date    PASS
  ✅  [WARNING ]  Validity              Amount              PASS
  ✅  [CRITICAL]  Completeness          PAN                 PASS
  ✅  [CRITICAL]  Completeness          Aadhaar             PASS

  ZONE 2 — Processing  (Transform & Enrich)
  ✅  [CRITICAL]  Uniqueness            Transaction_ID      PASS
  ✅  [WARNING ]  Consistency           Customer_ID         PASS

  ZONE 3 — Reporting  (Aggregate Analytics)
  ✅  [CRITICAL]  Accuracy              Amount              PASS
  ✅  [WARNING ]  Anomaly Detection     TABLE               PASS

  ✅  ALL CHECKS PASSED. Pipeline completed successfully.
```

### Scenario B — Corrupted Dataset

Null PAN and Aadhaar values (GRC/regulatory fields) trip the circuit breaker at Zone 1. Zones 2 and 3 are skipped entirely.

```
  🏦  BANKING_DQ_PIPELINE  —  Scenario-B_Corrupted-Dataset
  ──────────────────────────────────────────────────────────
  ZONE 1 — Ingestion  (Circuit Breaker Active)
  ✅  [WARNING ]  Timeliness            Transaction_Date    PASS
  ✅  [WARNING ]  Validity              Amount              PASS
  ❌  [CRITICAL]  Completeness          PAN                 FAIL  (35.0% rows violated)
  ❌  [CRITICAL]  Completeness          Aadhaar             FAIL  (15.0% rows violated)

  🔴  CIRCUIT BREAKER TRIPPED
      CRITICAL failure on column(s): ['PAN', 'Aadhaar'].
      ↳ Zone 2 (Processing) and Zone 3 (Reporting) skipped.

  🔴  PIPELINE HALTED — downstream zones were not executed.
```

---

## DQ Dimensions Covered

| Zone | Rule ID | Dimension | Column | Criticality |
|---|---|---|---|---|
| Ingestion | ING-001 | Timeliness | Transaction_Date | WARNING |
| Ingestion | ING-002 | Validity | Amount | WARNING |
| Ingestion | ING-003 | Completeness | PAN | **CRITICAL** |
| Ingestion | ING-004 | Completeness | Aadhaar | **CRITICAL** |
| Processing | PRO-001 | Uniqueness | Transaction_ID | **CRITICAL** |
| Processing | PRO-002 | Consistency | Customer_ID | WARNING |
| Reporting | REP-001 | Accuracy | Amount (sum) | **CRITICAL** |
| Reporting | REP-002 | Anomaly Detection | Row count | WARNING |

---

## Audit Logs

Every pipeline run writes a structured JSON audit log to `logs/audit/`:

```json
{
  "schema_version": "1.0",
  "scenario": "Scenario-A_Healthy-Dataset",
  "timestamp": "20260629_100755",
  "pipeline_halted": false,
  "summary": {
    "total_rules": 8,
    "passed": 8,
    "failed": 0,
    "critical_failures": 0
  },
  "records": [
    {
      "rule_id": "ING-001",
      "zone": "Ingestion",
      "dimension": "Timeliness",
      "column": "Transaction_Date",
      "status": "PASS",
      "criticality": "WARNING",
      "description": "Transaction dates must fall within the operational calendar year"
    }
  ]
}
```

---

## Extending the Framework

### Add a New Rule

Edit the relevant YAML file — no Python changes required:

```yaml
# config/rules/ingestion.yaml
- id: ING-005
  description: "Account number must match the 16-digit format"
  column: Account_Number
  expectation: expect_column_values_to_match_regex
  params:
    regex: "^[0-9]{16}$"
  dimension: Validity
  criticality: WARNING
```

### Add a New Zone

1. Create `config/rules/my_zone.yaml` with `suite_name` and `zone` fields
2. Call `pipeline._run_zone(context, "my_suite_name", df)` in `pipeline.py`

### Supported Parameter Types

| Type | How to declare | Example |
|---|---|---|
| Static | `params:` block | `min_value: 0, strict_min: true` |
| From pipeline config | `param_refs:` block | `min_value: expected_ledger_min` |
| Injected at runtime | `runtime_params:` list | `value_set` (from customer master) |

---

## Pipeline Configuration

`config/pipeline.yaml` controls all thresholds without touching rule files:

```yaml
data:
  expected_ledger_total: 50000.00   # Reconciliation target
  ledger_tolerance_pct: 0.02        # ±2% band
  historical_min_rows: 5            # Anomaly detection lower bound
  historical_max_rows: 1000         # Anomaly detection upper bound
  operational_date_min: "2024-01-01"
  operational_date_max: "2024-12-31"
```

---

## License

This project is intended for educational and demonstration purposes.
