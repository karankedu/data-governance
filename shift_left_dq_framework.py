"""
Shift-Left Data Quality Framework — Banking Use Case
Great Expectations 1.x  |  Python 3.11
Three Zones of Defense: Ingestion → Processing → Reporting
"""

import os
os.environ["TQDM_DISABLE"] = "1"

import io
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import uuid
import random
import logging
import warnings
import datetime
import contextlib
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import great_expectations as gx

logging.getLogger("great_expectations").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

# ── Constants ──────────────────────────────────────────────────────────────────
OPERATIONAL_DATE_MIN = datetime.datetime(2024, 1, 1)
OPERATIONAL_DATE_MAX = datetime.datetime(2024, 12, 31, 23, 59, 59)
EXPECTED_LEDGER_TOTAL = 50_000.00
LEDGER_TOLERANCE_PCT  = 0.02   # ±2% reconciliation band
HISTORICAL_MIN_ROWS   = 5
HISTORICAL_MAX_ROWS   = 1000

# ── Rule Registry ──────────────────────────────────────────────────────────────
# Maps "{expectation_type}__{column}" → zone / dimension / criticality metadata.
# GX carries no custom fields inside expectation objects; this registry is the
# single source of truth for DQ governance attributes.
RULE_REGISTRY: dict = {
    "ingestion_suite": {
        "expect_column_values_to_be_between__Transaction_Date": {
            "zone": "Ingestion", "dimension": "Timeliness",   "criticality": "WARNING",
        },
        "expect_column_values_to_be_between__Amount": {
            "zone": "Ingestion", "dimension": "Validity",     "criticality": "WARNING",
        },
        "expect_column_values_to_not_be_null__PAN": {
            "zone": "Ingestion", "dimension": "Completeness", "criticality": "CRITICAL",
        },
        "expect_column_values_to_not_be_null__Aadhaar": {
            "zone": "Ingestion", "dimension": "Completeness", "criticality": "CRITICAL",
        },
    },
    "processing_suite": {
        "expect_column_values_to_be_unique__Transaction_ID": {
            "zone": "Processing", "dimension": "Uniqueness",   "criticality": "CRITICAL",
        },
        "expect_column_values_to_be_in_set__Customer_ID": {
            "zone": "Processing", "dimension": "Consistency",  "criticality": "WARNING",
        },
    },
    "reporting_suite": {
        "expect_column_sum_to_be_between__Amount": {
            "zone": "Reporting", "dimension": "Accuracy",         "criticality": "CRITICAL",
        },
        "expect_table_row_count_to_be_between__TABLE": {
            "zone": "Reporting", "dimension": "Anomaly Detection", "criticality": "WARNING",
        },
    },
}

# ── Domain Types ───────────────────────────────────────────────────────────────

class CircuitBreakerTripped(Exception):
    pass


@dataclass
class AuditRecord:
    zone:             str
    dimension:        str
    expectation_type: str
    column:           str
    status:           str           # "PASS" | "FAIL"
    criticality:      str           # "CRITICAL" | "WARNING"
    unexpected_pct:   Optional[float]
    details:          str

# ── Mock Data Generation ───────────────────────────────────────────────────────

_CUSTOMER_IDS = [f"CUST{i:04d}" for i in range(1, 11)]


def _random_pan(rng: random.Random) -> str:
    a = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return (
        rng.choice(a) + rng.choice(a) + rng.choice(a) + rng.choice(a)
        + "P"
        + "".join(str(rng.randint(0, 9)) for _ in range(4))
        + rng.choice(a)
    )


def _random_aadhaar(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(12))


def _make_healthy_transactions(n: int = 20) -> pd.DataFrame:
    rng = random.Random(42)
    # Build amounts so they sum to exactly EXPECTED_LEDGER_TOTAL
    amounts = [round(rng.uniform(100, 4000), 2) for _ in range(n - 1)]
    remainder = round(EXPECTED_LEDGER_TOTAL - sum(amounts), 2)
    amounts.append(max(remainder, 100.0))

    rows = []
    for i in range(n):
        rows.append({
            "Transaction_ID":   str(uuid.UUID(int=rng.getrandbits(128))),
            "Customer_ID":      rng.choice(_CUSTOMER_IDS),
            "Amount":           amounts[i],
            "Transaction_Date": datetime.date(2024, rng.randint(1, 12), rng.randint(1, 28)),
            "PAN":              _random_pan(rng),
            "Aadhaar":          _random_aadhaar(rng),
            "Transaction_Type": rng.choice(["CREDIT", "DEBIT"]),
        })
    df = pd.DataFrame(rows)
    df["Transaction_Date"] = pd.to_datetime(df["Transaction_Date"])
    return df


def _make_customers() -> pd.DataFrame:
    rng = random.Random(99)
    return pd.DataFrame([
        {
            "Customer_ID":  cid,
            "Name":         f"Customer {cid}",
            "PAN":          _random_pan(rng),
            "Aadhaar":      _random_aadhaar(rng),
            "Account_Type": rng.choice(["SAVINGS", "CURRENT"]),
            "KYC_Status":   rng.choice(["VERIFIED", "PENDING"]),
        }
        for cid in _CUSTOMER_IDS
    ])


def generate_scenario_a() -> tuple:
    """Healthy dataset — all expectations pass cleanly across all zones."""
    return _make_healthy_transactions(), _make_customers()


def generate_scenario_b() -> tuple:
    """Corrupted dataset — deterministic PAN/Aadhaar nulls trigger the circuit breaker."""
    txn_df, cust_df = generate_scenario_a()
    txn_df = txn_df.copy()
    # Null out every 3rd row PAN (~35%) and every 7th row Aadhaar (~15%)
    txn_df.loc[list(range(0, len(txn_df), 3)), "PAN"]    = None
    txn_df.loc[list(range(1, len(txn_df), 7)), "Aadhaar"] = None
    return txn_df, cust_df

# ── GX Helpers ─────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _quiet():
    """Redirect stderr to suppress tqdm/GX progress noise during checkpoint runs."""
    old = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = old


def _get_batch_definition(context, suite_name: str, df: pd.DataFrame):
    ds    = context.data_sources.add_pandas(f"pandas_{suite_name}")
    asset = ds.add_dataframe_asset(f"asset_{suite_name}")
    return asset.add_batch_definition_whole_dataframe(f"batch_{suite_name}")

# ── Expectation Suite Builders ─────────────────────────────────────────────────

def _build_ingestion_suite(context) -> gx.ExpectationSuite:
    suite = gx.ExpectationSuite(name="ingestion_suite")
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="Transaction_Date",
            min_value=OPERATIONAL_DATE_MIN,
            max_value=OPERATIONAL_DATE_MAX,
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="Amount",
            min_value=0,
            strict_min=True,        # strictly > 0, not >= 0
        )
    )
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="PAN"))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="Aadhaar"))
    context.suites.add(suite)
    return suite


def _build_processing_suite(context, valid_customer_ids: list) -> gx.ExpectationSuite:
    suite = gx.ExpectationSuite(name="processing_suite")
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeUnique(column="Transaction_ID")
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="Customer_ID",
            value_set=valid_customer_ids,
        )
    )
    context.suites.add(suite)
    return suite


def _build_reporting_suite(context) -> gx.ExpectationSuite:
    total = EXPECTED_LEDGER_TOTAL
    band  = LEDGER_TOLERANCE_PCT
    suite = gx.ExpectationSuite(name="reporting_suite")
    suite.add_expectation(
        gx.expectations.ExpectColumnSumToBeBetween(
            column="Amount",
            min_value=round(total * (1 - band), 2),
            max_value=round(total * (1 + band), 2),
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectTableRowCountToBeBetween(
            min_value=HISTORICAL_MIN_ROWS,
            max_value=HISTORICAL_MAX_ROWS,
        )
    )
    context.suites.add(suite)
    return suite

# ── Result Parsing ─────────────────────────────────────────────────────────────

def _format_details(kwargs: dict) -> str:
    col   = kwargs.get("column", "TABLE")
    parts = []
    if kwargs.get("min_value") is not None:
        parts.append(f"min={str(kwargs['min_value'])[:10]}")
    if kwargs.get("max_value") is not None:
        parts.append(f"max={str(kwargs['max_value'])[:10]}")
    if "value_set" in kwargs:
        parts.append(f"value_set ({len(kwargs['value_set'])} allowed values)")
    if not parts:
        parts.append("not null")
    return f"{col}: {', '.join(parts)}"


def _parse_checkpoint_result(checkpoint_result, suite_name: str) -> list:
    records = []
    for suite_result in checkpoint_result.run_results.values():
        for exp_result in suite_result.results:
            exp_type = exp_result.expectation_config.type
            kwargs   = exp_result.expectation_config.kwargs or {}
            column   = kwargs.get("column", "TABLE")
            key      = f"{exp_type}__{column}"

            meta = RULE_REGISTRY.get(suite_name, {}).get(key, {
                "zone": suite_name, "dimension": "Unknown", "criticality": "WARNING",
            })

            result_dict = exp_result.result or {}
            records.append(AuditRecord(
                zone=meta["zone"],
                dimension=meta["dimension"],
                expectation_type=exp_type,
                column=column,
                status="PASS" if exp_result.success else "FAIL",
                criticality=meta["criticality"],
                unexpected_pct=result_dict.get("unexpected_percent"),
                details=_format_details(kwargs),
            ))
    return records

# ── Circuit Breaker ────────────────────────────────────────────────────────────

def _evaluate_circuit_breaker(records: list) -> None:
    failures = [r for r in records if r.status == "FAIL" and r.criticality == "CRITICAL"]
    if failures:
        cols = [r.column for r in failures]
        raise CircuitBreakerTripped(
            f"CRITICAL failure on column(s): {cols}. "
            f"Pipeline halted — raw data must not advance to downstream zones."
        )

# ── Console Output ─────────────────────────────────────────────────────────────

_W = 68   # display width


def _emoji(r: AuditRecord) -> str:
    if r.status == "PASS":
        return "✅"
    return "❌" if r.criticality == "CRITICAL" else "⚠️ "


def _print_zone_banner(name: str) -> None:
    print(f"\n  {'─' * _W}")
    print(f"  {name}")
    print(f"  {'─' * _W}")


def _print_record(r: AuditRecord) -> None:
    crit   = f"[{r.criticality:<8}]"
    dim    = f"{r.dimension:<20}"
    col    = f"{r.column:<18}"
    status = r.status
    pct    = (
        f"  ({r.unexpected_pct:.1f}% rows violated)"
        if r.unexpected_pct is not None and r.status == "FAIL"
        else ""
    )
    print(f"  {_emoji(r)}  {crit}  {dim}  {col}  {status}{pct}")


def _print_audit_trail(all_records: list, halted: bool = False) -> None:
    print(f"\n  {'═' * _W}")
    print(f"{'AUDIT TRAIL SUMMARY':^72}")
    print(f"  {'═' * _W}")
    print(f"  {'Zone':<12} {'Dimension':<22} {'Column':<18} {'Status':<6} Criticality")
    print(f"  {'─' * _W}")
    for r in all_records:
        print(
            f"  {r.zone:<12} {r.dimension:<22} {r.column:<18} "
            f"{_emoji(r)} {r.status:<6} {r.criticality}"
        )
    print()
    if halted:
        print("  🔴  PIPELINE HALTED — downstream zones were not executed.")
    else:
        fails = [r for r in all_records if r.status == "FAIL"]
        if fails:
            print(f"  ⚠️   Pipeline completed with {len(fails)} WARNING(s).")
        else:
            print("  ✅  ALL CHECKS PASSED. Pipeline completed successfully.")
    print(f"  {'═' * _W}\n")

# ── Zone Runners ───────────────────────────────────────────────────────────────

def _run_zone(context, suite_name: str, df: pd.DataFrame, builder, **kw) -> list:
    batch_def = _get_batch_definition(context, suite_name, df)
    suite     = builder(context, **kw)
    vd        = gx.ValidationDefinition(name=f"vd_{suite_name}", data=batch_def, suite=suite)
    context.validation_definitions.add(vd)
    cp        = gx.Checkpoint(name=f"cp_{suite_name}", validation_definitions=[vd])
    context.checkpoints.add(cp)
    with _quiet():
        result = cp.run(batch_parameters={"dataframe": df})
    return _parse_checkpoint_result(result, suite_name)


def run_ingestion_zone(context, txn_df: pd.DataFrame) -> list:
    return _run_zone(context, "ingestion_suite", txn_df, _build_ingestion_suite)


def run_processing_zone(context, txn_df: pd.DataFrame, customer_ids: list) -> list:
    return _run_zone(
        context, "processing_suite", txn_df,
        _build_processing_suite, valid_customer_ids=customer_ids,
    )


def run_reporting_zone(context, txn_df: pd.DataFrame) -> list:
    return _run_zone(context, "reporting_suite", txn_df, _build_reporting_suite)

# ── Pipeline Orchestrator ──────────────────────────────────────────────────────

def run_pipeline(txn_df: pd.DataFrame, cust_df: pd.DataFrame, scenario_label: str) -> None:
    print(f"\n  {'█' * _W}")
    print(f"  🏦  BANKING DQ PIPELINE  —  {scenario_label}")
    print(f"      Transactions: {len(txn_df):,} rows  |  Customers: {len(cust_df):,} rows")
    print(f"  {'█' * _W}")

    all_records: list = []
    halted            = False
    context           = gx.get_context(mode="ephemeral")

    try:
        _print_zone_banner("ZONE 1 — Ingestion  (Circuit Breaker Active)")
        ing = run_ingestion_zone(context, txn_df)
        all_records.extend(ing)
        for r in ing:
            _print_record(r)
        _evaluate_circuit_breaker(ing)   # raises AFTER records are captured in all_records

        _print_zone_banner("ZONE 2 — Processing  (Transform & Enrich)")
        proc = run_processing_zone(context, txn_df, cust_df["Customer_ID"].tolist())
        all_records.extend(proc)
        for r in proc:
            _print_record(r)

        _print_zone_banner("ZONE 3 — Reporting  (Aggregate Analytics)")
        rep = run_reporting_zone(context, txn_df)
        all_records.extend(rep)
        for r in rep:
            _print_record(r)

    except CircuitBreakerTripped as exc:
        halted = True
        print(f"\n  🔴  CIRCUIT BREAKER TRIPPED")
        print(f"      {exc}")
        print(f"      ↳ Zone 2 (Processing) and Zone 3 (Reporting) were skipped.")

    _print_audit_trail(all_records, halted=halted)

# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    banner = "▓" * 72
    print(f"\n{banner}")
    print("  SHIFT-LEFT DATA QUALITY FRAMEWORK  ·  Banking Demo")
    print("  Great Expectations 1.x  ·  Three Zones of Defense")
    print(f"{banner}")

    run_pipeline(*generate_scenario_a(), "Scenario A — Healthy Dataset")

    print(f"\n{'─' * 72}")
    print("  Starting Scenario B ...")
    print(f"{'─' * 72}")

    run_pipeline(*generate_scenario_b(), "Scenario B — Corrupted Dataset (PAN/Aadhaar Nulls)")
