"""Lazy, shared runtime construction for HTTP handlers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from backend.app.agents.graph import build_agent_graph
from backend.app.core.config import ProjectSettings, load_settings
from backend.app.db import repository
from backend.app.retrieval.service import search_study_memory
from backend.app.services.article_analysis import (
    build_article_analysis_chain,
    build_manual_term_classification_chain,
)


@dataclass(frozen=True)
class PharmaMateRuntime:
    settings: ProjectSettings
    model: Any
    article_chain: Any
    manual_term_chain: Any
    agent_graph: Any


@lru_cache(maxsize=1)
def get_runtime() -> PharmaMateRuntime:
    project_dir = Path(__file__).resolve().parents[3]
    settings = load_settings(project_dir)
    custom_dir = os.getenv("PHARMAMATE_DATA_DIR", "").strip()
    data_dir = Path(custom_dir).expanduser().resolve() if custom_dir else project_dir / "pharmamate_data"
    repository.configure_database(data_dir)

    model = ChatOpenAI(
        model=settings.model_name,
        temperature=0.2,
        timeout=90,
        max_retries=2,
        streaming=True,
        api_key=settings.openai_api_key,
    )
    search_client = None
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        from tavily import TavilyClient

        search_client = TavilyClient(api_key=tavily_key)
    graph = build_agent_graph(
        model=model,
        search_client=search_client,
        search_study_memory=search_study_memory,
        get_term_examples=repository.get_term_examples,
        get_saved_note=repository.get_saved_note,
    )
    return PharmaMateRuntime(
        settings=settings,
        model=model,
        article_chain=build_article_analysis_chain(model),
        manual_term_chain=build_manual_term_classification_chain(model),
        agent_graph=graph,
    )
