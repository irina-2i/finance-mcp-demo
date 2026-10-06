"""MCP server that gives an AI agent clean, trustworthy financial data.

Run with:  python -m finance_mcp.server
The agent never sees the messy raw exports. It gets a cleaned ledger and a few
well-described tools, plus a data quality report so it can be honest about caveats.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from finance_mcp import analysis
from finance_mcp.ledger import build_ledger

DEFAULT_RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
RAW_DIR = Path(os.environ.get("FINANCE_RAW_DIR", DEFAULT_RAW_DIR))

mcp = MCPServer(
    name="finance-data",
    instructions=(
        "Financial data for one company, cleaned from its Stripe and bank exports. "
        "All amounts are in SEK. Before giving conclusions, check get_data_quality_report "
        "and mention relevant caveats (for example uncategorized expenses)."
    ),
)


def _run(func, *args):
    """Turn bad input into a clear message for the agent instead of a crash."""
    ledger, _ = _load()
    try:
        return func(ledger, *args)
    except ValueError as err:
        raise ToolError(str(err)) from err


@lru_cache(maxsize=1)
def _load():
    """Clean the raw files once and keep the result in memory."""
    return build_ledger(RAW_DIR)


@mcp.tool()
def get_data_quality_report() -> dict:
    """What was cleaned, fixed or excluded when building the ledger from raw files.
    Call this first so you can mention data caveats in your answer."""
    _, report = _load()
    return report.as_dict()


@mcp.tool()
def get_monthly_summary(from_month: str | None = None, to_month: str | None = None) -> dict:
    """Revenue, expenses and net result per month in SEK.
    Months are formatted 'YYYY-MM'. Leave both empty to get every month."""
    return _run(analysis.monthly_summary, from_month, to_month)


@mcp.tool()
def get_expense_breakdown(month: str | None = None) -> dict:
    """Expenses grouped by category (salaries, rent, cloud, ai_models, software, marketing,
    uncategorized) with share of total. Give month as 'YYYY-MM', or leave empty for all months."""
    return _run(analysis.expense_breakdown, month)


@mcp.tool()
def get_burn_rate(months: int = 3) -> dict:
    """Average monthly net burn over the last N months (default 3)."""
    return _run(analysis.burn_rate, months)


@mcp.tool()
def get_runway(cash_balance_sek: float, months: int = 3) -> dict:
    """How many months the company can operate with the given cash balance (SEK),
    based on the average burn of the last N months."""
    return _run(analysis.runway, cash_balance_sek, months)


@mcp.tool()
def get_revenue_growth() -> dict:
    """Month over month revenue growth in percent, plus the average growth rate."""
    return _run(analysis.revenue_growth)


def main() -> None:
    mcp.run()  # stdio transport, which is what Claude Desktop uses


if __name__ == "__main__":
    main()
