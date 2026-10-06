"""Turn messy customer exports into one clean, analysis ready ledger.

Every row in the final ledger has the same shape:
    date (datetime) | month (YYYY-MM) | source | type (revenue/expense) | category | description | amount_sek

Amounts are positive for revenue and negative for expenses, always in SEK.
Each cleaning step also records what it changed, so the agent (and the customer)
can see *why* numbers look the way they do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Fixed demo rate. In production this would come from a daily FX rate source.
FX_TO_SEK = {"SEK": 1.0, "EUR": 11.5}

# Simple, transparent keyword rules. First match wins.
CATEGORY_RULES = [
    (r"\bLÖN\b", "salaries"),
    (r"\bHYRA\b", "rent"),
    (r"\bAWS\b|GOOGLE CLOUD|AZURE", "cloud"),
    (r"OPENAI|ANTHROPIC", "ai_models"),
    (r"GOOGLE WORKSPACE|FIGMA|FORTNOX|SLACK|NOTION", "software"),
    (r"LINKEDIN ADS|GOOGLE ADS|META ADS", "marketing"),
]

# Bank lines that are money moving between our own accounts, not income or cost.
INTERNAL_TRANSFERS = [r"STRIPE PAYOUT"]

LEDGER_COLUMNS = ["date", "month", "source", "type", "category", "description", "amount_sek"]


@dataclass
class QualityReport:
    """What the cleaning did. Shown to the user so nothing happens silently."""
    rows_read: dict[str, int] = field(default_factory=dict)
    issues: dict[str, int] = field(default_factory=dict)
    rows_in_ledger: int = 0
    uncategorized_descriptions: list[str] = field(default_factory=list)

    def add(self, issue: str, count: int) -> None:
        if count:
            self.issues[issue] = self.issues.get(issue, 0) + int(count)

    def as_dict(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "issues_fixed_or_excluded": self.issues,
            "rows_in_ledger": self.rows_in_ledger,
            "uncategorized_descriptions": self.uncategorized_descriptions,
        }


# ---------- helpers ----------

def parse_swedish_amount(text: str) -> float:
    """'-12 345,50' -> -12345.5. Handles normal and non-breaking spaces and the unicode minus."""
    cleaned = (
        str(text).strip()
        .replace("−", "-")      # unicode minus sign
        .replace(" ", "")       # non-breaking space
        .replace(" ", "")
        .replace(",", ".")
    )
    return float(cleaned)


def parse_mixed_date(text: str) -> pd.Timestamp:
    """Accept both 2026-01-05 and 05/01/2026 (day first, as Swedish banks write it)."""
    text = str(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return pd.Timestamp(text)
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        return pd.to_datetime(text, format="%d/%m/%Y")
    raise ValueError(f"Unknown date format: {text!r}")


def categorize(description: str) -> str:
    upper = description.upper()
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, upper):
            return category
    return "uncategorized"


# ---------- sources ----------

def clean_stripe(path: Path, report: QualityReport) -> pd.DataFrame:
    df = pd.read_csv(path)
    report.rows_read["stripe_payments"] = len(df)

    original_currency = df["currency"].copy()
    df["currency"] = df["currency"].str.strip().str.upper()
    report.add("stripe: currency codes standardized (e.g. 'sek' to 'SEK')",
               (original_currency != df["currency"]).sum())

    not_paid = df["status"] != "succeeded"
    report.add("stripe: failed or refunded payments excluded", not_paid.sum())
    df = df[~not_paid].copy()

    unknown_ccy = ~df["currency"].isin(FX_TO_SEK)
    report.add("stripe: payments in unsupported currency excluded", unknown_ccy.sum())
    df = df[~unknown_ccy].copy()

    df["date"] = pd.to_datetime(df["created"], unit="s", utc=True).dt.tz_localize(None)
    # Stripe stores amounts in minor units (öre / cents)
    df["amount_sek"] = (df["amount"] / 100) * df["currency"].map(FX_TO_SEK)
    report.add("stripe: EUR payments converted to SEK", (df["currency"] == "EUR").sum())

    return pd.DataFrame({
        "date": df["date"],
        "source": "stripe",
        "type": "revenue",
        "category": "subscriptions",
        "description": "Payment " + df["id"] + " from " + df["customer"],
        "amount_sek": df["amount_sek"].round(2),
    })


def clean_bank(path: Path, report: QualityReport) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str)
    report.rows_read["bank_transactions"] = len(df)

    df["date"] = df["Datum"].map(parse_mixed_date)
    report.add("bank: dates in DD/MM/YYYY format normalized",
               df["Datum"].str.contains("/").sum())
    df["amount_sek"] = df["Belopp"].map(parse_swedish_amount)
    df["description"] = df["Text"].str.strip()

    # Duplicates are only detectable after dates and amounts are normalized
    dupes = df.duplicated(subset=["date", "description", "amount_sek"])
    report.add("bank: duplicate rows removed", dupes.sum())
    df = df[~dupes].copy()

    internal = df["description"].str.upper().str.contains("|".join(INTERNAL_TRANSFERS))
    report.add("bank: Stripe payouts excluded (already counted as Stripe revenue)", internal.sum())
    df = df[~internal].copy()

    df["type"] = df["amount_sek"].map(lambda a: "revenue" if a > 0 else "expense")
    df["category"] = df["description"].map(categorize)
    uncategorized = df["category"] == "uncategorized"
    report.add("bank: transactions without a matching category rule", uncategorized.sum())
    report.uncategorized_descriptions = sorted(df.loc[uncategorized, "description"].unique())

    return pd.DataFrame({
        "date": df["date"],
        "source": "bank",
        "type": df["type"],
        "category": df["category"],
        "description": df["description"],
        "amount_sek": df["amount_sek"].round(2),
    })


def build_ledger(raw_dir: Path) -> tuple[pd.DataFrame, QualityReport]:
    report = QualityReport()
    ledger = pd.concat(
        [clean_stripe(raw_dir / "stripe_payments.csv", report),
         clean_bank(raw_dir / "bank_transactions.csv", report)],
        ignore_index=True,
    )
    ledger["month"] = ledger["date"].dt.strftime("%Y-%m")
    ledger = ledger[LEDGER_COLUMNS].sort_values("date").reset_index(drop=True)
    report.rows_in_ledger = len(ledger)
    return ledger, report
