from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import time
import importlib
import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = ROOT / "PharmaMate_2_0.ipynb"



def lexical_fixture_search(question: str, records: list[dict], limit: int = 5) -> list[dict]:
    """Approximate the 2.2 lexical lookup against an isolated evaluation corpus."""
    import re

    question_low = (question or "").casefold()
    tokens = [token for token in re.findall(r"[A-Za-z0-9가-힣]+", question_low) if len(token) > 1]
    ranked = []
    for record in records:
        aliases = record.get("aliases") or record.get("aliases_json") or []
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except json.JSONDecodeError:
                aliases = [aliases]
        names = list(aliases) + [record.get("term_name", "")]
        score = sum(4 for name in names if len(str(name).strip()) >= 2 and str(name).casefold() in question_low)
        definition = str(record.get("simple_definition", "")).casefold()
        score += sum(1 for token in tokens if token in definition)
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in ranked[:limit]]

def _read_notebook(revision: str | None) -> tuple[str, str]:
    if revision:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{revision}:PharmaMate_2_0.ipynb"],
                cwd=ROOT,
                stderr=subprocess.PIPE,
                text=False,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"기준선 노트북을 Git ref에서 읽지 못했습니다 ({revision}): {detail}") from exc
        return raw.decode("utf-8"), revision
    if not NOTEBOOK_PATH.is_file():
        raise FileNotFoundError(f"비교 후보 노트북을 찾지 못했습니다: {NOTEBOOK_PATH}")
    return NOTEBOOK_PATH.read_text(encoding="utf-8"), "working tree"


def _pin_graph_module(revision: str | None) -> None:
    """Load the graph implementation from the baseline ref or current worktree."""
    module_name = "backend.app.agents.graph"
    parent_name = "backend.app.agents"
    parent = importlib.import_module(parent_name)
    sys.modules.pop(module_name, None)
    if hasattr(parent, "graph"):
        delattr(parent, "graph")

    if revision:
        try:
            source = subprocess.check_output(
                ["git", "show", f"{revision}:backend/app/agents/graph.py"],
                cwd=ROOT,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip()
            raise RuntimeError(f"기준선 Agent 그래프를 읽지 못했습니다 ({revision}): {detail}") from exc
        module = types.ModuleType(module_name)
        module.__file__ = f"{revision}:backend/app/agents/graph.py"
        module.__package__ = parent_name
        sys.modules[module_name] = module
        setattr(parent, "graph", module)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    importlib.invalidate_caches()


@lru_cache(maxsize=4)
def _build_agent(notebook_text: str, label: str, graph_revision: str | None = None, memory_mode: str = "lexical") -> dict[str, Any]:
    """노트북의 LLM/Agent 셀만 실행합니다. 로컬 DB 셀과 Gradio UI는 실행하지 않습니다."""
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv가 없습니다. `pip install -r requirements.txt`를 실행하세요.") from exc

    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY가 없습니다. 프로젝트 .env 또는 환경 변수에 설정하세요.")

    notebook = json.loads(notebook_text)
    cells = notebook.get("cells", [])
    agent_setup = ""
    agent_graph = ""
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if "model = ChatOpenAI(" in source and "class ArticleAnalysis" in source:
            agent_setup = source
        if ("class AgentState" in source and "builder=StateGraph(AgentState)" in source) or "build_agent_graph(" in source:
            agent_graph = source
    if not agent_setup or not agent_graph:
        raise RuntimeError("PharmaMate 노트북에서 Agent 설정/그래프 셀을 찾지 못했습니다.")

    # 테스트는 샘플 fixture만 사용하며 Tavily나 SQLite에 접근하지 않도록 고정합니다.
    model_name = os.getenv("PHARMAMATE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    if "build_agent_graph(" in agent_graph:
        _pin_graph_module(graph_revision)

    fixture: dict[str, Any] = {"memory_records": []}
    namespace: dict[str, Any] = {
        "MODEL_NAME": model_name,
        "__name__": f"eval_{label}",
        "_eval_fixture": fixture,
        # The legacy graph cell expects os from the earlier notebook config cell.
        "os": os,
    }
    semantic_index: dict[str, Any] = {"fingerprint": None, "searcher": None}

    def fixture_memory_search(question: str, limit: int = 5, owner_id: str = "local"):
        records = fixture["memory_records"]
        if memory_mode == "semantic":
            if not records:
                return []
            from backend.app.retrieval.embeddings import get_embedding_provider
            from backend.app.retrieval.service import SemanticDocumentSearch

            fingerprint = json.dumps(records, ensure_ascii=False, sort_keys=True)
            if semantic_index["fingerprint"] != fingerprint:
                semantic_index["searcher"] = SemanticDocumentSearch(
                    records, get_embedding_provider(), owner_id=owner_id
                )
                semantic_index["fingerprint"] = fingerprint
            return semantic_index["searcher"].search(question, limit=limit)
        return lexical_fixture_search(question, records, limit)

    namespace["search_study_memory"] = fixture_memory_search
    namespace["get_term_examples"] = lambda _term_key, limit=8: []
    namespace["get_saved_note"] = lambda _term_key: ""
    # Pydantic resolves forward references through sys.modules[cls.__module__].
    # Register the dynamic namespace before executing notebook class definitions.
    runtime_module = types.ModuleType(namespace["__name__"])
    runtime_module.__dict__.update(namespace)
    sys.modules[runtime_module.__name__] = runtime_module
    namespace = runtime_module.__dict__
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(agent_setup, f"{label}:agent_setup", "exec"), namespace)
        os.environ["TAVILY_API_KEY"] = ""
        exec(compile(agent_graph, f"{label}:agent_graph", "exec"), namespace)
    return namespace


def _run(
    notebook_text: str,
    label: str,
    case: dict[str, Any],
    graph_revision: str | None = None,
    memory_mode: str = "lexical",
) -> dict[str, Any]:
    namespace = _build_agent(notebook_text, label, graph_revision, memory_mode)
    # agent_memory가 읽는 학습 기록은 개인 DB가 아니라 사례별 fixture에서만 가져옵니다.
    namespace["_eval_fixture"]["memory_records"] = case.get("memory_records", [])

    request = {
        "question": case["question"],
        "article": case.get("article", ""),
        "term": case.get("term", ""),
        "history": case.get("history", ""),
    }
    started = time.perf_counter()
    result = namespace["agent_graph"].invoke(request)
    elapsed = time.perf_counter() - started
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "route": result.get("route", ""),
        "validator": "미적용(2.2 기준선)" if "validation_status" not in result else result.get("validation_status", "미제공"),
        "validation_status": result.get("validation_status"),
        "validation_retries": result.get("validation_retries", 0),
        "unsupported_claims": result.get("unsupported_claims", []),
        "latency_seconds": elapsed,
        "tokens": None,
        "cost": None,
    }


def run_baseline(case: dict[str, Any], *, revision: str | None = "HEAD") -> dict[str, Any]:
    source, label = _read_notebook(revision or "HEAD")
    return _run(source, f"baseline_{label}", case, graph_revision=revision or "HEAD")


def run_candidate(case: dict[str, Any], *, revision: str | None = None) -> dict[str, Any]:
    source, label = _read_notebook(None)
    result = _run(source, f"candidate_{label}", case, memory_mode="semantic")
    status = result.get("validation_status", "미제공")
    retries = int(result.get("validation_retries", 0))
    result["validator"] = f"{status} (수정 {retries}회)"
    return result
