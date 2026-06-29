"""Generic GX engine: builds suites from declarative rule configs and runs checkpoints."""
from __future__ import annotations

import contextlib
import io
import logging
from typing import Any

import great_expectations as gx
import pandas as pd

from .config import DataConfig, RuleConfig, ZoneConfig

logger = logging.getLogger(__name__)


def _to_pascal_case(snake: str) -> str:
    """Convert snake_case expectation name to the PascalCase GX class name."""
    return "".join(w.capitalize() for w in snake.split("_"))


def _get_expectation_class(expectation_type: str):
    cls_name = _to_pascal_case(expectation_type)
    cls = getattr(gx.expectations, cls_name, None)
    if cls is None:
        raise ValueError(
            f"GX expectation '{expectation_type}' not found. "
            f"Looked for: gx.expectations.{cls_name}"
        )
    return cls


def _resolve_params(
    rule: RuleConfig,
    data_config: DataConfig,
    runtime_params: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge three sources of parameters for a rule:
      1. params       — static values declared in YAML
      2. param_refs   — values pulled from DataConfig properties at build time
      3. runtime_params — values injected by the pipeline at run time (e.g. value_set)
    """
    params = dict(rule.params)

    for param_name, config_attr in rule.param_refs.items():
        value = getattr(data_config, config_attr, None)
        if value is None:
            raise ValueError(
                f"Rule {rule.id}: param_ref '{config_attr}' not found on DataConfig"
            )
        params[param_name] = value

    for param_name in rule.runtime_params:
        if param_name not in runtime_params:
            raise ValueError(
                f"Rule {rule.id}: runtime param '{param_name}' was not supplied. "
                f"Available: {list(runtime_params.keys())}"
            )
        params[param_name] = runtime_params[param_name]

    return params


class DQEngine:
    """
    Translates a ZoneConfig (YAML rules) into a GX ExpectationSuite.

    Adding a new DQ check = adding a rule to a YAML file.
    No Python changes required.
    """

    def __init__(self, data_config: DataConfig) -> None:
        self._data_config = data_config

    def build_suite(
        self,
        zone_config: ZoneConfig,
        runtime_params: dict[str, Any] | None = None,
    ) -> gx.ExpectationSuite:
        runtime_params = runtime_params or {}
        suite = gx.ExpectationSuite(name=zone_config.suite_name)

        for rule in zone_config.rules:
            cls    = _get_expectation_class(rule.expectation)
            params = _resolve_params(rule, self._data_config, runtime_params)
            kwargs: dict[str, Any] = {}
            if rule.column:
                kwargs["column"] = rule.column
            kwargs.update(params)

            suite.add_expectation(cls(**kwargs))
            logger.debug("Rule %s registered: %s", rule.id, rule.expectation)

        logger.info(
            "Suite '%s' built: %d rule(s)", zone_config.suite_name, len(zone_config.rules)
        )
        return suite

    @staticmethod
    def run_checkpoint(
        context: gx.DataContext,
        suite_name: str,
        suite: gx.ExpectationSuite,
        df: pd.DataFrame,
    ):
        """Register datasource + asset, attach suite, run checkpoint, return raw result."""
        ds        = context.data_sources.add_pandas(f"pandas_{suite_name}")
        asset     = ds.add_dataframe_asset(f"asset_{suite_name}")
        batch_def = asset.add_batch_definition_whole_dataframe(f"batch_{suite_name}")

        context.suites.add(suite)
        vd = gx.ValidationDefinition(name=f"vd_{suite_name}", data=batch_def, suite=suite)
        context.validation_definitions.add(vd)
        cp = gx.Checkpoint(name=f"cp_{suite_name}", validation_definitions=[vd])
        context.checkpoints.add(cp)

        with contextlib.redirect_stderr(io.StringIO()):   # suppress tqdm noise
            return cp.run(batch_parameters={"dataframe": df})
