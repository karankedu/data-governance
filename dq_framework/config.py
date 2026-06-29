"""Configuration models (Pydantic) and YAML loaders."""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Rule & Zone Config ─────────────────────────────────────────────────────────

class RuleConfig(BaseModel):
    id:             str
    description:    str = ""
    column:         Optional[str] = None    # None for table-level expectations
    expectation:    str                     # GX expectation type (snake_case)
    params:         dict[str, Any] = {}     # static parameters passed directly to GX
    param_refs:     dict[str, str] = {}     # param_name → DataConfig property name
    runtime_params: list[str] = []          # param names injected at pipeline runtime
    dimension:      str
    criticality:    Literal["CRITICAL", "WARNING"]


class ZoneConfig(BaseModel):
    suite_name: str
    zone:       str
    rules:      list[RuleConfig]


# ── Pipeline Config ────────────────────────────────────────────────────────────

class DataConfig(BaseModel):
    expected_ledger_total:  float
    ledger_tolerance_pct:   float
    historical_min_rows:    int
    historical_max_rows:    int
    operational_date_min:   str     # "YYYY-MM-DD"
    operational_date_max:   str     # "YYYY-MM-DD"

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def expected_ledger_min(self) -> float:
        return round(self.expected_ledger_total * (1 - self.ledger_tolerance_pct), 2)

    @property
    def expected_ledger_max(self) -> float:
        return round(self.expected_ledger_total * (1 + self.ledger_tolerance_pct), 2)

    @property
    def operational_date_min_dt(self) -> datetime.datetime:
        return datetime.datetime.strptime(self.operational_date_min, "%Y-%m-%d")

    @property
    def operational_date_max_dt(self) -> datetime.datetime:
        d = datetime.datetime.strptime(self.operational_date_max, "%Y-%m-%d")
        return d.replace(hour=23, minute=59, second=59)


class PipelineInfo(BaseModel):
    name:        str
    version:     str
    description: str = ""


class LoggingConfig(BaseModel):
    level: str = "INFO"


class OutputConfig(BaseModel):
    audit_log_dir: str = "logs/audit"
    console:       bool = True


class PipelineConfig(BaseModel):
    pipeline: PipelineInfo
    data:     DataConfig
    logging:  LoggingConfig = LoggingConfig()
    output:   OutputConfig  = OutputConfig()


# ── Loaders ────────────────────────────────────────────────────────────────────

def load_pipeline_config(path: str | Path) -> PipelineConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = PipelineConfig.model_validate(raw)
    logger.debug("Pipeline config loaded from %s", path)
    return cfg


def load_zone_config(path: str | Path) -> ZoneConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = ZoneConfig.model_validate(raw)
    logger.debug("Zone config loaded: %s (%d rules)", cfg.suite_name, len(cfg.rules))
    return cfg


def load_all_zone_configs(rules_dir: str | Path) -> dict[str, ZoneConfig]:
    """Load all *.yaml files from rules_dir, keyed by suite_name."""
    configs: dict[str, ZoneConfig] = {}
    for yaml_file in sorted(Path(rules_dir).glob("*.yaml")):
        cfg = load_zone_config(yaml_file)
        configs[cfg.suite_name] = cfg
    return configs
