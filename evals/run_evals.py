"""Evals for the finance MCP server, in three layers.

1. Tool evals     - every tool returns the expected number for a known question.
2. Safety evals   - malicious or nonsensical input is rejected with a clear error, not executed.
3. Agent evals    - Claude answers real questions through the MCP tools; we check that it
                    called the right tool, used the right numbers and did not invent any.
                    Runs only when ANTHROPIC_API_KEY is set (it costs a few cents).

Usage:
    python evals/run_evals.py            # layers 1 and 2, plus 3 if a key is set
    EVAL_MODEL=claude-... python evals/run_evals.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())
MODEL = os.environ.get("EVAL_MODEL", "claude-sonnet-4-5")
SYSTEM = ("You are a finance assistant for one company. Use the tools for every number you give. "
          "Never state a figure that did not come from a tool. Answer briefly.")


def dig(data, path: str):
    """Follow 'a.0.b' through dicts and lists. Keys may contain dots, so try the longest match first."""
    parts = path.split(".")
    while parts:
        for n in range(len(parts), 0, -1):
            key = ".".join(parts[:n])
            if isinstance(data, list) and key.isdigit():
                data, parts = data[int(key)], parts[n:]
                break
            if isinstance(data, dict) and key in data:
                data, parts = data[key], parts[n:]
                break
        else:
            raise KeyError(path)
    return data


def numbers_in(text: str) -> list[float]:
    """'156 760,68 SEK', '156,761' and '9.6 months' -> floats."""
    found = []
    for raw in re.findall(r"\d[\d\s,. ]*\d|\d", text):
        s = raw.replace(" ", " ").strip()
        if re.fullmatch(r"\d{1,3}([ ,]\d{3})+([.,]\d+)?", s):          # thousands separators
            s = re.sub(r"[ ,](?=\d{3}\b)", "", s)
        s = s.replace(" ", "").replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "", s.count(".") - 1)
        try:
            found.append(float(s))
        except ValueError:
            pass
    text_m = re.findall(r"(\d+(?:[.,]\d+)?)\s*(million|m\b)", text, flags=re.I)
    found += [float(v.replace(",", ".")) * 1_000_000 for v, _ in text_m]
    return found


def is_error(res) -> bool:
    """MCP SDK 2.x uses is_error, 1.x used isError."""
    return bool(getattr(res, "is_error", None) or getattr(res, "isError", False))


def close(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= max(abs(b) * rel, 0.051)


async def run_tool_and_safety(session: ClientSession) -> list[tuple[str, bool, str]]:
    results = []
    for case in CASES["tool_cases"]:
        res = await session.call_tool(case["tool"], case["args"])
        try:
            got = dig(json.loads(res.content[0].text), case["path"])
            ok = got == case["expected"] if isinstance(case["expected"], str) else close(got, case["expected"])
            results.append((case["id"], ok, f"got {got}, expected {case['expected']}"))
        except Exception as err:  # noqa: BLE001
            results.append((case["id"], False, f"error: {err}"))
    for case in CASES["safety_cases"]:
        res = await session.call_tool(case["tool"], case["args"])
        rejected = is_error(res)
        msg = res.content[0].text[:80] if res.content else ""
        results.append((case["id"], rejected, "rejected: " + msg if rejected else "NOT rejected"))
    return results


async def ask_agent(session: ClientSession, tools: list[dict], question: str) -> tuple[str, list[str]]:
    import anthropic
    client = anthropic.Anthropic()
    messages, used = [{"role": "user", "content": question}], []
    for _ in range(8):
        reply = client.messages.create(model=MODEL, max_tokens=800, system=SYSTEM,
                                       tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": reply.content})
        calls = [b for b in reply.content if b.type == "tool_use"]
        if not calls:
            return "".join(b.text for b in reply.content if b.type == "text"), used
        results = []
        for call in calls:
            used.append(call.name)
            res = await session.call_tool(call.name, call.input)
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": res.content[0].text if res.content else "",
                            "is_error": is_error(res)})
        messages.append({"role": "user", "content": results})
    return "(no final answer)", used


async def run_agent(session: ClientSession) -> list[tuple[str, bool, str]]:
    listed = await session.list_tools()
    tools = [{"name": t.name, "description": t.description or "",
              "input_schema": getattr(t, "input_schema", None) or t.inputSchema} for t in listed.tools]
    results = []
    for case in CASES["agent_cases"]:
        answer, used = await ask_agent(session, tools, case["question"])
        nums, low = numbers_in(answer), answer.lower()
        problems = []
        problems += [f"missing tool {t}" for t in case.get("expected_tools", []) if t not in used]
        problems += [f"missing number {n}" for n in case.get("expected_numbers", [])
                     if not any(close(x, n) for x in nums)]
        problems += [f"missing word '{w}'" for w in case.get("expected_words", []) if w not in low]
        problems += [f"invented number {n}" for n in case.get("forbidden_numbers", [])
                     if any(close(x, n) for x in nums)]
        results.append((case["id"], not problems, "; ".join(problems) or f"tools: {', '.join(used)}"))
    return results


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "finance_mcp.server"],
                                   env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")})
    with open(os.devnull, "w") as quiet:  # hide server logs, the report below is what matters
        async with stdio_client(params, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                results = await run_tool_and_safety(session)
                if os.environ.get("ANTHROPIC_API_KEY"):
                    results += await run_agent(session)
                else:
                    print("Agent evals skipped: set ANTHROPIC_API_KEY to run them.\n")

    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
