"""Small, testable financial metrics on top of the clean ledger.

Each function returns plain dicts and includes a short "method" note, so an agent
can explain how a number was calculated instead of just stating it.
"""

from __future__ import annotations

import re

import pandas as pd

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _check_month(value: str | None, name: str) -> None:
    if value is not None and not MONTH_RE.match(value):
        raise ValueError(f"{name} must look like 'YYYY-MM', got {value!r}")


def monthly_summary(ledger: pd.DataFrame, from_month: str | None = None,
                    to_month: str | None = None) -> dict:
    _check_month(from_month, "from_month")
    _check_month(to_month, "to_month")
    df = ledger
    if from_month:
        df = df[df["month"] >= from_month]
    if to_month:
        df = df[df["month"] <= to_month]

    revenue = df[df["type"] == "revenue"].groupby("month")["amount_sek"].sum()
    expenses = df[df["type"] == "expense"].groupby("month")["amount_sek"].sum()
    months = sorted(set(revenue.index) | set(expenses.index))
    rows = []
    for m in months:
        r, e = float(revenue.get(m, 0.0)), float(expenses.get(m, 0.0))
        rows.append({"month": m, "revenue_sek": round(r, 2),
                     "expenses_sek": round(-e, 2), "net_sek": round(r + e, 2)})
    return {
        "months": rows,
        "method": "Revenue = successful Stripe payments plus positive bank lines "
                  "(Stripe payouts excluded). Expenses = negative bank lines. All in SEK.",
    }


def expense_breakdown(ledger: pd.DataFrame, month: str | None = None) -> dict:
    _check_month(month, "month")
    df = ledger[ledger["type"] == "expense"]
    if month:
        df = df[df["month"] == month]
    if df.empty:
        return {"month": month, "categories": [], "total_expenses_sek": 0.0}
    by_cat = (-df.groupby("category")["amount_sek"].sum()).sort_values(ascending=False)
    total = float(by_cat.sum())
    return {
        "month": month or "all months",
        "total_expenses_sek": round(total, 2),
        "categories": [
            {"category": c, "amount_sek": round(float(v), 2), "share_pct": round(100 * v / total, 1)}
            for c, v in by_cat.items()
        ],
    }


def burn_rate(ledger: pd.DataFrame, months: int = 3) -> dict:
    if not 1 <= months <= 24:
        raise ValueError("months must be between 1 and 24")
    rows = monthly_summary(ledger)["months"][-months:]
    avg_net = sum(r["net_sek"] for r in rows) / len(rows)
    return {
        "months_used": [r["month"] for r in rows],
        "average_monthly_net_sek": round(avg_net, 2),
        "average_monthly_burn_sek": round(max(-avg_net, 0.0), 2),
        "is_profitable": avg_net >= 0,
        "method": f"Average of monthly net (revenue minus expenses) over the last {len(rows)} months.",
    }


def runway(ledger: pd.DataFrame, cash_balance_sek: float, months: int = 3) -> dict:
    if cash_balance_sek < 0:
        raise ValueError("cash_balance_sek cannot be negative")
    burn = burn_rate(ledger, months)
    monthly_burn = burn["average_monthly_burn_sek"]
    runway_months = None if monthly_burn == 0 else round(cash_balance_sek / monthly_burn, 1)
    return {
        "cash_balance_sek": cash_balance_sek,
        "average_monthly_burn_sek": monthly_burn,
        "runway_months": runway_months,
        "note": "No burn: the company covers its costs, runway is not limited by cash."
                if runway_months is None else
                "Runway = cash balance / average monthly burn. Assumes burn stays flat.",
        "based_on_months": burn["months_used"],
    }


def revenue_growth(ledger: pd.DataFrame) -> dict:
    rows = monthly_summary(ledger)["months"]
    out, prev = [], None
    for r in rows:
        growth = None if not prev else round(100 * (r["revenue_sek"] - prev) / prev, 1)
        out.append({"month": r["month"], "revenue_sek": r["revenue_sek"], "mom_growth_pct": growth})
        prev = r["revenue_sek"]
    growths = [g["mom_growth_pct"] for g in out if g["mom_growth_pct"] is not None]
    return {
        "months": out,
        "average_mom_growth_pct": round(sum(growths) / len(growths), 1) if growths else None,
        "method": "Month over month change in total revenue (SEK).",
    }
