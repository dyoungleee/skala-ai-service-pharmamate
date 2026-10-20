"""Measure direct retrieval versus a session-scoped MCP stdio tool call."""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from backend.app.db import repository
from backend.app.mcp_server import search_learning_records_for_session


def p50(values: list[float]) -> float:
    return round(statistics.median(values), 3) if values else 0.0


def run() -> dict:
    previous_db_path = repository.DB_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="pharmamate-mcp-eval-") as temp_dir:
            repository.configure_database(temp_dir)
            session_id, token = "synthetic-mcp-session", "synthetic-mcp-session-token"
            repository.create_study_session(session_id, token)
            repository.save_session_study_record(
                session_id,
                {"term": "항체-약물 접합체 (ADC)", "category": "Modality",
                 "simple_definition": "항체가 약물을 표적 세포에 전달합니다."},
                "합성 MCP 벤치마크 메모입니다.",
            )
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "backend.app.mcp_server"],
                env={
                    "PHARMAMATE_SESSION_TOKEN": token,
                    "PHARMAMATE_DATA_DIR": temp_dir,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                cwd=ROOT,
            )

            async def measure() -> dict:
                async with Client(params) as client:
                    tools = await client.list_tools()
                    resources = await client.list_resources()
                    prompts = await client.list_prompts()
                    query = "항체 약물 접합체"
                    expected = search_learning_records_for_session(session_id, query, 3)
                    direct_times, mcp_times = [], []
                    successes = 0
                    for _ in range(30):
                        start = time.perf_counter()
                        direct = search_learning_records_for_session(session_id, query, 3)
                        direct_times.append((time.perf_counter() - start) * 1000)
                        start = time.perf_counter()
                        result = await client.call_tool("search_learning_records", {
                            "query": query, "limit": 3,
                        })
                        mcp_times.append((time.perf_counter() - start) * 1000)
                        if not result.is_error and result.structured_content:
                            successes += 1
                        if direct != expected:
                            raise AssertionError("direct retrieval changed during the fixture run")
                    final_result = await client.call_tool("search_learning_records", {
                        "query": query, "limit": 3,
                    })
                    return {
                        "tool_count": len(tools.tools),
                        "resource_count": len(resources.resources),
                        "prompt_count": len(prompts.prompts),
                        "repeats": len(mcp_times),
                        "direct_p50_ms": p50(direct_times),
                        "mcp_stdio_p50_ms": p50(mcp_times),
                        "mcp_successes": successes,
                        "same_result": final_result.structured_content == {"result": expected},
                    }

            return asyncio.run(measure())
    finally:
        repository.DB_PATH = previous_db_path


if __name__ == "__main__":
    result = run()
    output = ROOT / "eval" / "results" / "mcp_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"MCP primitives: tools={result['tool_count']}, resources={result['resource_count']}, "
        f"prompts={result['prompt_count']}"
    )
    print(
        f"30 synthetic retrievals: direct p50={result['direct_p50_ms']:.3f}ms, "
        f"MCP stdio p50={result['mcp_stdio_p50_ms']:.3f}ms, "
        f"success={result['mcp_successes']}/30, same_result={result['same_result']}"
    )
    print("Raw fixture results: eval/results/mcp_latest.json")
