"""Audit record model, result parser, console formatter, and JSON audit writer."""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .config import RuleConfig, ZoneConfig

logger = logging.getLogger(__name__)

_W = 68   # console display width


# ── Domain Model ───────────────────────────────────────────────────────────────

@dataclass
class AuditRecord:
    rule_id:          str
    zone:             str
    dimension:        str
    expectation_type: str
    column:           str
    status:           str               # "PASS" | "FAIL"
    criticality:      str               # "CRITICAL" | "WARNING"
    unexpected_pct:   Optional[float]   # None for table-level expectations
    description:      str


# ── Result Parser ──────────────────────────────────────────────────────────────

def parse_results(checkpoint_result, zone_config: ZoneConfig) -> list[AuditRecord]:
    """
    Convert a raw GX CheckpointResult into structured AuditRecords.
    Rule metadata (dimension, criticality, description) is pulled from ZoneConfig
    using a (expectation_type, column) lookup — no separate registry needed.
    """
    rule_index: dict[tuple[str, str], RuleConfig] = {
        (rule.expectation, rule.column or "TABLE"): rule
        for rule in zone_config.rules
    }

    records: list[AuditRecord] = []
    for suite_result in checkpoint_result.run_results.values():
        for exp_result in suite_result.results:
            exp_type = exp_result.expectation_config.type
            kwargs   = exp_result.expectation_config.kwargs or {}
            column   = kwargs.get("column", "TABLE")

            rule = rule_index.get((exp_type, column))
            if rule is None:
                logger.warning(
                    "No rule found for (%s, %s) in zone '%s'",
                    exp_type, column, zone_config.suite_name,
                )

            result_dict = exp_result.result or {}
            records.append(AuditRecord(
                rule_id=rule.id if rule else "UNKNOWN",
                zone=zone_config.zone,
                dimension=rule.dimension if rule else "Unknown",
                expectation_type=exp_type,
                column=column,
                status="PASS" if exp_result.success else "FAIL",
                criticality=rule.criticality if rule else "WARNING",
                unexpected_pct=result_dict.get("unexpected_percent"),
                description=rule.description if rule else "",
            ))
    return records


# ── Console Formatting ─────────────────────────────────────────────────────────

def _emoji(r: AuditRecord) -> str:
    if r.status == "PASS":
        return "✅"
    return "❌" if r.criticality == "CRITICAL" else "⚠️ "


def print_zone_banner(zone_name: str) -> None:
    print(f"\n  {'─' * _W}")
    print(f"  {zone_name}")
    print(f"  {'─' * _W}")


def print_record(r: AuditRecord) -> None:
    crit   = f"[{r.criticality:<8}]"
    dim    = f"{r.dimension:<20}"
    col    = f"{r.column:<18}"
    pct    = (
        f"  ({r.unexpected_pct:.1f}% rows violated)"
        if r.unexpected_pct is not None and r.status == "FAIL"
        else ""
    )
    print(f"  {_emoji(r)}  {crit}  {dim}  {col}  {r.status}{pct}")


def print_audit_trail(records: list[AuditRecord], halted: bool = False) -> None:
    print(f"\n  {'═' * _W}")
    print(f"{'AUDIT TRAIL SUMMARY':^72}")
    print(f"  {'═' * _W}")
    print(
        f"  {'Rule ID':<9} {'Zone':<12} {'Dimension':<20} {'Column':<18} "
        f"{'Status':<6} Criticality"
    )
    print(f"  {'─' * _W}")
    for r in records:
        print(
            f"  {r.rule_id:<9} {r.zone:<12} {r.dimension:<20} {r.column:<18} "
            f"{_emoji(r)} {r.status:<6} {r.criticality}"
        )
    print()
    if halted:
        print("  🔴  PIPELINE HALTED — downstream zones were not executed.")
    else:
        fails = [r for r in records if r.status == "FAIL"]
        print(
            f"  ⚠️   Pipeline completed with {len(fails)} WARNING(s)."
            if fails else
            "  ✅  ALL CHECKS PASSED. Pipeline completed successfully."
        )
    print(f"  {'═' * _W}\n")


# ── JSON Audit Log ─────────────────────────────────────────────────────────────

def write_audit_log(
    records: list[AuditRecord],
    scenario: str,
    log_dir: str,
    halted: bool = False,
) -> Path:
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    ts           = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name    = "".join(c if c.isalnum() or c in "-_" else "_" for c in scenario)
    path         = log_dir_path / f"audit_{safe_name}_{ts}.json"

    payload = {
        "schema_version": "1.0",
        "scenario":       scenario,
        "timestamp":      ts,
        "pipeline_halted": halted,
        "summary": {
            "total_rules":       len(records),
            "passed":            sum(1 for r in records if r.status == "PASS"),
            "failed":            sum(1 for r in records if r.status == "FAIL"),
            "critical_failures": sum(
                1 for r in records if r.status == "FAIL" and r.criticality == "CRITICAL"
            ),
        },
        "records": [asdict(r) for r in records],
    }

    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("Audit log written → %s", path)
    return path
