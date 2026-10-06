"""Tests use tiny hand-written files, so every expected number can be checked by hand."""

from pathlib import Path

import pandas as pd
import pytest

from finance_mcp import analysis
from finance_mcp.ledger import build_ledger, categorize, parse_mixed_date, parse_swedish_amount

STRIPE = """id,created,amount,currency,status,customer
py_1,1767268800,450000,sek,succeeded,cus_a
py_2,1767268800,10000,EUR,succeeded,cus_b
py_3,1767268800,450000,sek,failed,cus_c
py_4,1769947200,600000,SEK,succeeded,cus_a
"""
# 1767268800 = 2026-01-01 12:00 UTC, 1769947200 = 2026-02-01 12:00 UTC

BANK = """Datum;Text;Belopp
2026-01-25;LÖN LÖNEUTBETALNING;-100 000,00
25/01/2026;LÖN LÖNEUTBETALNING;-100 000,00
2026-01-05;AWS EMEA;-10 000,50
2026-01-28;STRIPE PAYOUT;50 000,00
2026-02-10;ESPRESSO HOUSE;-250,00
2026-02-25;LÖN LÖNEUTBETALNING;-100 000,00
"""


@pytest.fixture()
def ledger(tmp_path: Path):
    (tmp_path / "stripe_payments.csv").write_text(STRIPE)
    (tmp_path / "bank_transactions.csv").write_text(BANK, encoding="utf-8")
    return build_ledger(tmp_path)


def test_parse_swedish_amount():
    assert parse_swedish_amount("-12 345,50") == -12345.5
    assert parse_swedish_amount("− 1 000,00") == -1000.0


def test_parse_mixed_date():
    assert parse_mixed_date("05/01/2026") == pd.Timestamp("2026-01-05")
    assert parse_mixed_date("2026-01-05") == pd.Timestamp("2026-01-05")
    with pytest.raises(ValueError):
        parse_mixed_date("Jan 5 2026")


def test_categorize():
    assert categorize("LÖN LÖNEUTBETALNING") == "salaries"
    assert categorize("Anthropic API") == "ai_models"
    assert categorize("ESPRESSO HOUSE") == "uncategorized"


def test_cleaning_rules(ledger):
    df, report = ledger
    issues = report.issues
    assert issues["stripe: failed or refunded payments excluded"] == 1
    assert issues["bank: duplicate rows removed"] == 1           # same salary, two date formats
    assert issues["bank: Stripe payouts excluded (already counted as Stripe revenue)"] == 1
    assert "STRIPE PAYOUT" not in set(df["description"])
    assert report.uncategorized_descriptions == ["ESPRESSO HOUSE"]


def test_monthly_summary(ledger):
    df, _ = ledger
    jan, feb = analysis.monthly_summary(df)["months"]
    # Jan revenue: 4 500 SEK + 100 EUR * 11.5 = 5 650. Expenses: 100 000 + 10 000,50
    assert jan == {"month": "2026-01", "revenue_sek": 5650.0,
                   "expenses_sek": 110000.5, "net_sek": -104350.5}
    assert feb["revenue_sek"] == 6000.0
    assert feb["expenses_sek"] == 100250.0


def test_burn_and_runway(ledger):
    df, _ = ledger
    burn = analysis.burn_rate(df, months=2)
    # net: Jan -104 350,50 and Feb -94 250 -> average burn 99 300,25
    assert burn["average_monthly_burn_sek"] == 99300.25
    rw = analysis.runway(df, cash_balance_sek=993002.5, months=2)
    assert rw["runway_months"] == 10.0


def test_bad_input_is_rejected(ledger):
    df, _ = ledger
    with pytest.raises(ValueError):
        analysis.monthly_summary(df, from_month="January")
    with pytest.raises(ValueError):
        analysis.burn_rate(df, months=0)
    with pytest.raises(ValueError):
        analysis.runway(df, cash_balance_sek=-1)
