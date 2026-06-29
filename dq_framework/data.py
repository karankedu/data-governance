"""Deterministic mock data generators for banking demo scenarios."""
from __future__ import annotations

import datetime
import random
import uuid

import pandas as pd

_CUSTOMER_IDS   = [f"CUST{i:04d}" for i in range(1, 11)]
_LEDGER_TOTAL   = 50_000.00


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


def make_transactions(n: int = 20) -> pd.DataFrame:
    """Generate a clean transaction dataset (seeded for reproducibility)."""
    rng     = random.Random(42)
    amounts = [round(rng.uniform(100, 4000), 2) for _ in range(n - 1)]
    amounts.append(max(round(_LEDGER_TOTAL - sum(amounts), 2), 100.0))

    rows = [
        {
            "Transaction_ID":   str(uuid.UUID(int=rng.getrandbits(128))),
            "Customer_ID":      rng.choice(_CUSTOMER_IDS),
            "Amount":           amounts[i],
            "Transaction_Date": datetime.date(2024, rng.randint(1, 12), rng.randint(1, 28)),
            "PAN":              _random_pan(rng),
            "Aadhaar":          _random_aadhaar(rng),
            "Transaction_Type": rng.choice(["CREDIT", "DEBIT"]),
        }
        for i in range(n)
    ]
    df = pd.DataFrame(rows)
    df["Transaction_Date"] = pd.to_datetime(df["Transaction_Date"])
    return df


def make_customers() -> pd.DataFrame:
    """Generate the Customer Master reference dataset."""
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


def scenario_a() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scenario A: healthy dataset — all DQ checks should pass."""
    return make_transactions(), make_customers()


def scenario_b() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scenario B: corrupted — null PAN/Aadhaar triggers the circuit breaker."""
    txn_df, cust_df = scenario_a()
    txn_df = txn_df.copy()
    txn_df.loc[list(range(0, len(txn_df), 3)), "PAN"]     = None   # ~35% null
    txn_df.loc[list(range(1, len(txn_df), 7)), "Aadhaar"]  = None   # ~15% null
    return txn_df, cust_df
