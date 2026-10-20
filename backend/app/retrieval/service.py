"""Hybrid semantic retrieval over SQLite-backed, rebuildable memory vectors."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime
from typing import Any, Iterable

from backend.app.db import repository
from backend.app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)
DEFAULT_OWNER_ID = "local"
MAX_CHUNK_CHARS = 1600
CHUNK_OVERLAP_CHARS = 160


def normalize_documents(documents: Iterable[dict], owner_id: str = DEFAULT_OWNER_ID) -> list[dict]:
    normalized = []
    for item in documents:
        item_owner = str(item.get("owner_id") or DEFAULT_OWNER_ID)
        if item_owner != owner_id:
            continue
        source_type = str(item.get("source_type") or "term")
        source_id = str(item.get("source_id") or item.get("term_key") or item.get("record_id") or "")
        term_key = str(item.get("term_key") or "")
        title = str(item.get("title") or item.get("term_name") or source_id or source_type)
        content = str(item.get("content") or "").strip()
        aliases = item.get("aliases") or item.get("aliases_json") or []
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except json.JSONDecodeError:
                aliases = [aliases]
        supplements = [
            f"용어: {item.get('term_name', '')}" if item.get("term_name") else "",
            f"분류: {item.get('category', '')}" if item.get("category") else "",
            f"정의: {item.get('simple_definition', '')}" if item.get("simple_definition") else "",
            f"별칭: {', '.join(map(str, aliases))}" if aliases else "",
        ]
        missing_metadata = [part for part in supplements if part and part.casefold() not in content.casefold()]
        content = "\n".join(part for part in [content, *missing_metadata] if part).strip()
        if not content:
            continue
        record_id = str(item.get("record_id") or f"{source_type}:{source_id}")
        normalized.append({
            "owner_id": owner_id,
            "source_type": source_type,
            "source_id": source_id,
            "record_id": record_id,
            "term_key": term_key,
            "title": title,
            "content": content,
            "source_url": str(item.get("source_url") or item.get("url") or ""),
        })
    return normalized


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("。", start, end), text.rfind("\n", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return chunks


def chunk_documents(documents: Iterable[dict], owner_id: str = DEFAULT_OWNER_ID) -> list[dict]:
    chunks = []
    for document in normalize_documents(documents, owner_id):
        for index, text in enumerate(_split_text(document["content"])):
            chunk_id = hashlib.sha256(
                f"{owner_id}\0{document['source_type']}\0{document['source_id']}\0{index}".encode("utf-8")
            ).hexdigest()
            content = f"{document['title']}\n{text}"
            chunks.append({
                **document,
                "chunk_id": chunk_id,
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            })
    return chunks


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _lexical_overlap(query: str, content: str) -> float:
    query_tokens = {token for token in re.findall(r"[a-z0-9가-힣]+", query.casefold()) if len(token) > 1}
    if not query_tokens:
        return 0.0
    content_low = content.casefold()
    return sum(token in content_low for token in query_tokens) / len(query_tokens)


def _rank_chunks(chunks: list[dict], query_vector: list[float], limit: int, min_score: float, query: str = "") -> list[dict]:
    ranked = []
    for chunk in chunks:
        vector = chunk.get("embedding") or chunk.get("embedding_json")
        if isinstance(vector, str):
            try:
                vector = json.loads(vector)
            except json.JSONDecodeError:
                continue
        semantic = cosine_similarity(query_vector, vector or [])
        lexical = _lexical_overlap(query, chunk.get("content", ""))
        score = 0.70 * semantic + 0.30 * lexical
        if score < min_score:
            continue
        record_id = chunk.get("record_id") or f"{chunk.get('source_type', 'memory')}:{chunk.get('source_id', '')}"
        ranked.append({**chunk, "record_id": record_id, "semantic_score": semantic, "score": score})
    ranked.sort(key=lambda row: row["score"], reverse=True)
    seen = set()
    results = []
    for row in ranked:
        diversity_key = row.get("term_key") or row["record_id"]
        if diversity_key in seen:
            continue
        seen.add(diversity_key)
        results.append({key: value for key, value in row.items() if key not in {"embedding", "embedding_json", "query_terms"}})
        if len(results) >= limit:
            break
    return results


class SemanticDocumentSearch:
    """Reusable in-memory semantic searcher for isolated evaluation fixtures."""
    def __init__(self, documents: Iterable[dict], embedding_provider: EmbeddingProvider,
                 owner_id: str = DEFAULT_OWNER_ID):
        self.owner_id = owner_id
        self.embedding_provider = embedding_provider
        self.chunks = chunk_documents(documents, owner_id)
        vectors = embedding_provider.embed_documents([chunk["content"] for chunk in self.chunks]) if self.chunks else []
        if len(vectors) != len(self.chunks):
            raise ValueError("임베딩 결과 개수가 문서 청크 수와 일치하지 않습니다.")
        self.chunks = [{**chunk, "embedding": vector} for chunk, vector in zip(self.chunks, vectors)]

    def search(self, question: str, limit: int = 5, min_score: float = 0.20) -> list[dict]:
        if not question.strip() or not self.chunks or limit <= 0:
            return []
        vector = self.embedding_provider.embed_query(question)
        return _rank_chunks(self.chunks, vector, limit, min_score, question)


def search_documents(documents: Iterable[dict], question: str, *,
                     embedding_provider: EmbeddingProvider | None = None,
                     owner_id: str = DEFAULT_OWNER_ID, limit: int = 5,
                     min_score: float = 0.20) -> list[dict]:
    if not question.strip() or limit <= 0:
        return []
    provider = embedding_provider or get_embedding_provider()
    return SemanticDocumentSearch(documents, provider, owner_id).search(question, limit, min_score)


def _refresh_persistent_index(owner_id: str, provider: EmbeddingProvider) -> list[dict]:
    source_chunks = chunk_documents(repository.get_memory_documents(owner_id), owner_id)
    stored_rows = repository.get_memory_embedding_rows(owner_id)
    stored_by_id = {row["chunk_id"]: row for row in stored_rows}
    active_ids = [chunk["chunk_id"] for chunk in source_chunks]
    changed = [chunk for chunk in source_chunks if not (
        chunk["chunk_id"] in stored_by_id
        and stored_by_id[chunk["chunk_id"]]["content_hash"] == chunk["content_hash"]
        and stored_by_id[chunk["chunk_id"]]["embedding_model"] == provider.model_name
    )]
    vectors = provider.embed_documents([chunk["content"] for chunk in changed]) if changed else []
    if len(vectors) != len(changed):
        raise ValueError("임베딩 결과 개수가 변경 문서 수와 일치하지 않습니다.")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    replacement_rows = []
    for chunk, vector in zip(changed, vectors):
        replacement_rows.append({
            **chunk,
            "embedding_model": provider.model_name,
            "embedding_json": json.dumps(vector, separators=(",", ":")),
            "updated_at": now,
        })
    repository.replace_memory_embeddings(owner_id, replacement_rows, active_ids)
    return repository.get_memory_embedding_rows(owner_id)


def search_study_memory(question: str, limit: int = 5, owner_id: str = DEFAULT_OWNER_ID,
                        embedding_provider: EmbeddingProvider | None = None) -> list[dict]:
    """Retrieve local memories semantically; fall back to existing lexical search on API failure."""
    if not question.strip() or limit <= 0:
        return []
    if owner_id != DEFAULT_OWNER_ID:
        return []
    documents = repository.get_memory_documents(owner_id)
    if not documents:
        return []
    try:
        provider = embedding_provider or get_embedding_provider()
        rows = _refresh_persistent_index(owner_id, provider)
        query_vector = provider.embed_query(question)
        return _rank_chunks(rows, query_vector, limit, 0.20, question)
    except Exception as exc:
        logger.warning("Semantic memory retrieval failed (%s); using lexical fallback", type(exc).__name__)
        return repository.search_study_memory(question, limit)
