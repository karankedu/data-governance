"""DQPipeline: loads configs, orchestrates zones, manages circuit breaker."""
from __future__ import annotations

import logging
from pathlib import Path

import great_expectations as gx
import pandas as pd

from .config import PipelineConfig, ZoneConfig, load_all_zone_configs, load_pipeline_config
from .engine import DQEngine
from .reporting import (
    AuditRecord,
    parse_results,
    print_audit_trail,
    print_record,
    print_zone_banner,
    write_audit_log,
)

logger = logging.getLogger(__name__)

_W = 68


# ── Circuit Breaker ────────────────────────────────────────────────────────────

class CircuitBreakerTripped(Exception):
    pass


def _check_circuit_breaker(records: list[AuditRecord]) -> None:
    failures = [r for r in records if r.status == "FAIL" and r.criticality == "CRITICAL"]
    if failures:
        cols = [r.column for r in failures]
        raise CircuitBreakerTripped(
            f"CRITICAL failure on column(s): {cols}. "
            f"Raw data must not advance to downstream zones."
        )


# ── Pipeline ───────────────────────────────────────────────────────────────────

class DQPipeline:
    """
    Config-driven data quality pipeline.

    All DQ rules live in YAML — no Python changes needed to add, remove,
    or modify checks.  The engine resolves rule configs to GX expectations
    at runtime.

    Usage:
        pipeline = DQPipeline.from_config("config/pipeline.yaml", "config/rules/")
        records  = pipeline.run(txn_df, cust_df, scenario="production")
    """

    def __init__(
        self,
        pipeline_config: PipelineConfig,
        zone_configs: dict[str, ZoneConfig],
    ) -> None:
        self.pipeline_config = pipeline_config
        self.zone_configs    = zone_configs
        self._engine         = DQEngine(pipeline_config.data)

    @classmethod
    def from_config(cls, pipeline_yaml: str, rules_dir: str) -> "DQPipeline":
        """Factory: load pipeline + all zone configs from disk."""
        pipeline_config = load_pipeline_config(pipeline_yaml)
        zone_configs    = load_all_zone_configs(rules_dir)
        logger.info(
            "Pipeline '%s' v%s loaded — %d zone(s), %d total rule(s)",
            pipeline_config.pipeline.name,
            pipeline_config.pipeline.version,
            len(zone_configs),
            sum(len(z.rules) for z in zone_configs.values()),
        )
        return cls(pipeline_config, zone_configs)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run_zone(
        self,
        context: gx.DataContext,
        suite_name: str,
        df: pd.DataFrame,
        runtime_params: dict | None = None,
    ) -> list[AuditRecord]:
        zone_config = self.zone_configs[suite_name]
        suite       = self._engine.build_suite(zone_config, runtime_params)
        result      = DQEngine.run_checkpoint(context, suite_name, suite, df)
        records     = parse_results(result, zone_config)
        return records

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        txn_df: pd.DataFrame,
        cust_df: pd.DataFrame,
        scenario: str = "default",
    ) -> list[AuditRecord]:
        """
        Execute all three zones in sequence.

        Raises CircuitBreakerTripped internally; the exception is caught and
        surfaced in the audit trail — callers always receive the partial record list.
        """
        cfg         = self.pipeline_config
        all_records: list[AuditRecord] = []
        halted      = False
        context     = gx.get_context(mode="ephemeral")

        print(f"\n  {'█' * _W}")
        print(f"  🏦  {cfg.pipeline.name.upper()}  —  {scenario}")
        print(
            f"      Pipeline v{cfg.pipeline.version}  "
            f"|  Transactions: {len(txn_df):,}  |  Customers: {len(cust_df):,}"
        )
        print(f"  {'█' * _W}")

        logger.info("Run started: scenario='%s'", scenario)

        try:
            # ── Zone 1: Ingestion ──────────────────────────────────────────────
            print_zone_banner("ZONE 1 — Ingestion  (Circuit Breaker Active)")
            ing = self._run_zone(context, "ingestion_suite", txn_df)
            all_records.extend(ing)
            for r in ing:
                print_record(r)
            _check_circuit_breaker(ing)     # raises only AFTER records are captured

            # ── Zone 2: Processing ─────────────────────────────────────────────
            print_zone_banner("ZONE 2 — Processing  (Transform & Enrich)")
            proc = self._run_zone(
                context, "processing_suite", txn_df,
                runtime_params={"value_set": cust_df["Customer_ID"].tolist()},
            )
            all_records.extend(proc)
            for r in proc:
                print_record(r)

            # ── Zone 3: Reporting ──────────────────────────────────────────────
            print_zone_banner("ZONE 3 — Reporting  (Aggregate Analytics)")
            rep = self._run_zone(context, "reporting_suite", txn_df)
            all_records.extend(rep)
            for r in rep:
                print_record(r)

        except CircuitBreakerTripped as exc:
            halted = True
            print(f"\n  🔴  CIRCUIT BREAKER TRIPPED")
            print(f"      {exc}")
            print(f"      ↳ Zone 2 (Processing) and Zone 3 (Reporting) skipped.")
            logger.error("Circuit breaker tripped: %s", exc)

        print_audit_trail(all_records, halted=halted)

        if cfg.output.audit_log_dir:
            log_path = write_audit_log(
                all_records, scenario, cfg.output.audit_log_dir, halted
            )
            print(f"  📄  Audit log → {log_path}\n")

        logger.info(
            "Run complete: scenario='%s', halted=%s, rules_evaluated=%d",
            scenario, halted, len(all_records),
        )
        return all_records
