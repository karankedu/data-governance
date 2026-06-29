"""CLI entry point for the Banking Data Quality Framework."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ["TQDM_DISABLE"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Silence GX before it loads
logging.getLogger("great_expectations").setLevel(logging.CRITICAL)

from dq_framework.data import scenario_a, scenario_b
from dq_framework.pipeline import DQPipeline


def setup_logging(level: str, log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)-28s] %(levelname)-8s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"{log_dir}/dq_pipeline.log", encoding="utf-8"),
        ],
        force=True,
    )
    logging.getLogger("great_expectations").setLevel(logging.CRITICAL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dq-framework",
        description="Banking Shift-Left Data Quality Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py                          # run both scenarios
  python main.py --scenario a             # healthy dataset only
  python main.py --scenario b             # corrupted dataset only
  python main.py --log-level DEBUG        # verbose output
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=["a", "b", "both"],
        default="both",
        help="Scenario to run (default: both)",
    )
    parser.add_argument(
        "--pipeline-config",
        default="config/pipeline.yaml",
        metavar="PATH",
        help="Path to pipeline.yaml (default: config/pipeline.yaml)",
    )
    parser.add_argument(
        "--rules-dir",
        default="config/rules",
        metavar="DIR",
        help="Directory containing zone rule YAML files (default: config/rules)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level, "logs")

    pipeline = DQPipeline.from_config(args.pipeline_config, args.rules_dir)

    banner = "▓" * 72
    print(f"\n{banner}")
    print("  SHIFT-LEFT DATA QUALITY FRAMEWORK  ·  Banking Demo")
    print("  Great Expectations 1.x  ·  Configuration-Driven  ·  Three Zones")
    print(f"{banner}")

    if args.scenario in ("a", "both"):
        txn_df, cust_df = scenario_a()
        pipeline.run(txn_df, cust_df, scenario="Scenario-A_Healthy-Dataset")

    if args.scenario == "both":
        print(f"\n{'─' * 72}")

    if args.scenario in ("b", "both"):
        txn_df, cust_df = scenario_b()
        pipeline.run(txn_df, cust_df, scenario="Scenario-B_Corrupted-Dataset")


if __name__ == "__main__":
    main()
