"""Measure sequential and concurrent independent source tasks with fixed I/O delay."""
from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def measure() -> dict:
    repeats = 30
    task_delay_seconds = 0.08
    current = 0
    peak_concurrency = 0
    current_lock = threading.Lock()

    def source(name: str) -> dict[str, str]:
        nonlocal current, peak_concurrency
        with current_lock:
            current += 1
            peak_concurrency = max(peak_concurrency, current)
        try:
            time.sleep(task_delay_seconds)
            return {name: f"synthetic-{name}-result"}
        finally:
            with current_lock:
                current -= 1

    sequential_times, parallel_times = [], []
    sequential_outputs, parallel_outputs = [], []
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="parallel-eval") as pool:
        for _ in range(repeats):
            start = time.perf_counter()
            sequential = {**source("memory"), **source("web")}
            sequential_times.append((time.perf_counter() - start) * 1000)
            sequential_outputs.append(sequential)

            start = time.perf_counter()
            memory_future = pool.submit(source, "memory")
            web_future = pool.submit(source, "web")
            parallel = {**memory_future.result(), **web_future.result()}
            parallel_times.append((time.perf_counter() - start) * 1000)
            parallel_outputs.append(parallel)

    return {
        "repeats": repeats,
        "fixture_io_delay_ms_per_source": task_delay_seconds * 1000,
        "sequential_p50_ms": round(statistics.median(sequential_times), 2),
        "parallel_p50_ms": round(statistics.median(parallel_times), 2),
        "latency_reduction_percent": round(
            (1 - statistics.median(parallel_times) / statistics.median(sequential_times)) * 100, 2
        ),
        "peak_branch_concurrency": peak_concurrency,
        "all_outputs_equal": sequential_outputs == parallel_outputs,
        "sequential_successes": sum(bool(row.get("memory") and row.get("web")) for row in sequential_outputs),
        "parallel_successes": sum(bool(row.get("memory") and row.get("web")) for row in parallel_outputs),
        "max_source_workers": 8,
    }


if __name__ == "__main__":
    result = measure()
    output = ROOT / "eval" / "results" / "parallel_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"30 synthetic memory+web pairs (80ms each): sequential p50={result['sequential_p50_ms']:.2f}ms, "
        f"parallel p50={result['parallel_p50_ms']:.2f}ms, "
        f"reduction={result['latency_reduction_percent']:.1f}%, "
        f"same_outputs={result['all_outputs_equal']}, peak_concurrency={result['peak_branch_concurrency']}"
    )
    print("Raw fixture results: eval/results/parallel_latest.json")
