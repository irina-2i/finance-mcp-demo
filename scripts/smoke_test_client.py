"""Start the MCP server like Claude Desktop would (stdio) and call every tool once."""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "finance_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            calls = [
                ("get_data_quality_report", {}),
                ("get_monthly_summary", {"from_month": "2026-08"}),
                ("get_runway", {"cash_balance_sek": 1500000}),
                ("get_monthly_summary", {"from_month": "August"}),  # should return an error, not crash
            ]
            for name, args in calls:
                res = await session.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                print(f"\n{name}({args}) error={res.isError if hasattr(res,'isError') else getattr(res,'is_error',None)}\n{text[:400]}")

asyncio.run(main())
