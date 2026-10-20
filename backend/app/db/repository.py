"""SQLite 학습 기록 저장소. 경로 설정 후 명시적으로 스키마를 초기화합니다."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DB_PATH: Path | None = None

def normalize_term(term: str) -> str:
    text = (term or "").strip()
    acronyms = re.findall(r"\(([A-Za-z][A-Za-z0-9+-]{1,15})\)", text)
    if acronyms:
        return acronyms[-1].casefold()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+-]{1,15}", text):
        return text.casefold()
    return re.sub(r"[\s_\-]+", "", text).casefold()

def aliases_for(term: dict) -> List[str]:
    names = [term.get("term", "")] + list(term.get("aliases") or [])
    names.extend(re.findall(r"\(([A-Za-z][A-Za-z0-9+-]{1,15})\)", term.get("term", "")))
    if "(" in term.get("term", ""):
        names.append(term["term"].split("(")[0].strip())
    return list(dict.fromkeys(x.strip() for x in names if x and x.strip()))

def connect_db():
    if DB_PATH is None:
        raise RuntimeError("DB 경로가 설정되지 않았습니다. configure_database()를 먼저 호출하세요.")
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS learned_terms (
            term_key TEXT PRIMARY KEY,
            term_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            category TEXT NOT NULL,
            simple_definition TEXT NOT NULL,
            first_learned_at TEXT NOT NULL,
            last_reviewed_at TEXT,
            review_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS read_articles (
            article_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_url TEXT,
            article_type TEXT,
            summary TEXT,
            key_issue TEXT,
            entities_json TEXT NOT NULL,
            read_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS term_examples (
            term_key TEXT NOT NULL,
            article_id TEXT NOT NULL,
            context TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(term_key, article_id)
        );
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            chunk_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            term_key TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_owner
            ON memory_embeddings(owner_id);
        """)

def now_local():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def get_learned_rows():
    with connect_db() as conn:
        return [dict(x) for x in conn.execute("SELECT * FROM learned_terms ORDER BY first_learned_at DESC")]

def get_saved_term(term: dict):
    keys = {normalize_term(x) for x in aliases_for(term)}
    for row in get_learned_rows():
        other = {row['term_key']} | {normalize_term(x) for x in json.loads(row['aliases_json'])}
        if keys & other:
            return row
    return None

def normalize_article_title(title: str) -> str:
    text=unicodedata.normalize('NFKC',str(title or '')).casefold().strip()
    parts=re.split(r'\s*<\s*',text,maxsplit=1)
    if len(parts)>1 and any(tag in parts[1] for tag in ('기사본문','제약','바이오','산업','기업')):
        text=parts[0]
    text=re.sub(r'\s*[-–—|｜]\s*(?:팜뉴스|히트뉴스|메디파나뉴스|약업신문|의학신문|데일리팜|뉴스1|뉴시스|연합뉴스)\s*$','',text)
    return re.sub(r'[^0-9a-z가-힣]+','',text)

def article_titles_match(left: str, right: str) -> bool:
    if not left or not right or min(len(left),len(right))<10:
        return False
    if left==right:
        return True
    shorter,longer=sorted((left,right),key=len)
    return len(shorter)>=24 and longer.startswith(shorter) and len(shorter)/len(longer)>=0.75

def canonical_article_url(url: str) -> str:
    try:
        parsed=urlparse(str(url or '').strip())
        if parsed.scheme.lower() not in ('http','https') or not parsed.hostname:
            return ''
        host=parsed.hostname.lower()
        if host.startswith('www.'):
            host=host[4:]
        port=parsed.port
        if port and not ((parsed.scheme.lower()=='http' and port==80) or
                         (parsed.scheme.lower()=='https' and port==443)):
            host=f'{host}:{port}'
        tracking={'fbclid','gclid','dclid','mc_cid','mc_eid','_ga'}
        query=[(key,value) for key,value in parse_qsl(parsed.query,keep_blank_values=True)
               if not key.lower().startswith('utm_') and key.lower() not in tracking]
        query.sort()
        return urlunparse((parsed.scheme.lower(),host,parsed.path.rstrip('/') or '/',
                           '',urlencode(query,doseq=True),''))
    except ValueError:
        return ''

def save_term_card(term: dict, article_id: str, article_url: str):
    prev = get_saved_term(term)
    key = prev["term_key"] if prev else normalize_term(term["term"])
    if not key:
        raise ValueError("저장할 용어가 없습니다.")
    aliases = list(dict.fromkeys((json.loads(prev['aliases_json']) if prev else []) + aliases_for(term)))
    with connect_db() as conn:
        conn.execute("""INSERT INTO learned_terms
           (term_key,term_name,aliases_json,category,simple_definition,first_learned_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(term_key) DO UPDATE SET aliases_json=excluded.aliases_json,
           category=excluded.category, simple_definition=excluded.simple_definition""",
           (key, prev['term_name'] if prev else term['term'], json.dumps(aliases,ensure_ascii=False),
            term['category'], term['simple_definition'], now_local()))
        conn.execute("""INSERT OR IGNORE INTO term_examples
           (term_key,article_id,context,source_url,created_at) VALUES (?,?,?,?,?)""",
           (key, article_id, term.get('article_context',''), article_url, now_local()))
    return bool(prev), key

def save_read_article(state: dict):
    analysis = state.get('analysis') or {}
    aid = state.get('article_id')
    if not aid or not analysis:
        raise ValueError("먼저 기사를 분석해 주세요.")
    title=state.get('title','기사')
    source_url=state.get('url','')
    title_key=normalize_article_title(title)
    source_key=canonical_article_url(source_url)
    with connect_db() as conn:
        existing=conn.execute('SELECT title,source_url FROM read_articles').fetchall()
        for saved in existing:
            same_url=bool(source_key and source_key==canonical_article_url(saved['source_url']))
            same_title=article_titles_match(title_key,normalize_article_title(saved['title']))
            if same_url or same_title:
                return False
        cur = conn.execute("""INSERT OR IGNORE INTO read_articles
          (article_id,title,source_url,article_type,summary,key_issue,entities_json,read_at)
          VALUES (?,?,?,?,?,?,?,?)""",
          (aid,title,source_url,analysis.get('article_type',''),
           analysis.get('one_line_summary',''),analysis.get('key_issue',''),
           json.dumps(analysis.get('key_entities',[]),ensure_ascii=False),now_local()))
        if cur.rowcount != 1:
            return False
        for term in analysis.get('key_terms', []):
            prev = get_saved_term(term)
            if prev:
                conn.execute("""INSERT OR IGNORE INTO term_examples
                  (term_key,article_id,context,source_url,created_at) VALUES (?,?,?,?,?)""",
                  (prev['term_key'],aid,term.get('article_context',''),state.get('url',''),now_local()))
    return cur.rowcount == 1

def get_recent_articles(limit=20):
    with connect_db() as conn:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM read_articles ORDER BY read_at DESC LIMIT ?", (limit,))]

def get_term_examples(term_key, limit=8):
    with connect_db() as conn:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM term_examples WHERE term_key=? ORDER BY created_at DESC LIMIT ?", (term_key,limit))]

def get_memory_documents(owner_id: str = "local") -> list[dict]:
    """Return source-of-truth learning records for the current local owner scope.

    The current app is single-user. Unknown scopes return no records until the
    session/ownership migration adds owner columns to source tables.
    """
    if owner_id != "local":
        return []
    documents: list[dict] = []
    with connect_db() as conn:
        terms = [dict(row) for row in conn.execute(
            "SELECT * FROM learned_terms ORDER BY term_name")]
        for term in terms:
            aliases = json.loads(term.get("aliases_json") or "[]")
            title = f"학습 용어: {term['term_name']}"
            content = (
                f"용어: {term['term_name']}\n분류: {term['category']}\n"
                f"정의: {term['simple_definition']}\n별칭: {', '.join(aliases)}"
            )
            documents.append({
                "owner_id": owner_id, "source_type": "term",
                "source_id": term["term_key"], "record_id": f"term:{term['term_key']}",
                "term_key": term["term_key"], "title": title, "content": content,
                "source_url": "",
            })
        for row in conn.execute("""SELECT n.term_key,n.note,t.term_name
            FROM term_notes n JOIN learned_terms t USING(term_key)
            ORDER BY n.updated_at DESC"""):
            documents.append({
                "owner_id": owner_id, "source_type": "note",
                "source_id": row["term_key"], "record_id": f"note:{row['term_key']}",
                "term_key": row["term_key"], "title": f"학습 메모: {row['term_name']}",
                "content": str(row["note"] or ""), "source_url": "",
            })
        for row in conn.execute("""SELECT q.qa_id,q.term_key,q.article_id,q.question,q.answer,
            t.term_name FROM term_qa q JOIN learned_terms t USING(term_key)
            ORDER BY q.created_at DESC"""):
            documents.append({
                "owner_id": owner_id, "source_type": "qa",
                "source_id": row["qa_id"], "record_id": f"qa:{row['qa_id']}",
                "term_key": row["term_key"], "title": f"학습 Q&A: {row['term_name']}",
                "content": f"질문: {row['question']}\n답변: {row['answer']}",
                "source_url": "",
            })
        for row in conn.execute("""SELECT e.term_key,e.article_id,e.context,e.source_url,
            t.term_name,a.title AS article_title FROM term_examples e
            JOIN learned_terms t USING(term_key)
            LEFT JOIN read_articles a USING(article_id)
            ORDER BY e.created_at DESC"""):
            source_id = f"{row['term_key']}:{row['article_id']}"
            documents.append({
                "owner_id": owner_id, "source_type": "article_context",
                "source_id": source_id, "record_id": f"article_context:{source_id}",
                "term_key": row["term_key"],
                "title": f"기사 맥락: {row['article_title'] or row['term_name']}",
                "content": str(row["context"] or ""),
                "source_url": str(row["source_url"] or ""),
            })
        for row in conn.execute("""SELECT article_id,title,source_url,article_type,
            summary,key_issue,entities_json FROM read_articles ORDER BY read_at DESC"""):
            entities = json.loads(row["entities_json"] or "[]")
            content = (
                f"기사 제목: {row['title']}\n유형: {row['article_type']}\n"
                f"요약: {row['summary']}\n핵심 이슈: {row['key_issue']}\n"
                f"주요 대상: {', '.join(entities)}"
            )
            documents.append({
                "owner_id": owner_id, "source_type": "article",
                "source_id": row["article_id"], "record_id": f"article:{row['article_id']}",
                "term_key": "", "title": f"읽은 기사: {row['title']}",
                "content": content, "source_url": str(row["source_url"] or ""),
            })
    return [document for document in documents if document["content"].strip()]


def get_memory_embedding_rows(owner_id: str = "local") -> list[dict]:
    with connect_db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM memory_embeddings WHERE owner_id=?", (owner_id,))]


def replace_memory_embeddings(owner_id: str, rows: list[dict], active_chunk_ids: list[str]) -> None:
    """Atomically replace changed vectors and remove stale chunks for one owner."""
    with connect_db() as conn:
        if active_chunk_ids:
            placeholders = ",".join("?" for _ in active_chunk_ids)
            conn.execute(
                f"DELETE FROM memory_embeddings WHERE owner_id=? AND chunk_id NOT IN ({placeholders})",
                [owner_id, *active_chunk_ids],
            )
        else:
            conn.execute("DELETE FROM memory_embeddings WHERE owner_id=?", (owner_id,))
        conn.executemany("""INSERT OR REPLACE INTO memory_embeddings
            (chunk_id,owner_id,source_type,source_id,term_key,title,content,content_hash,
             embedding_model,embedding_json,updated_at)
            VALUES (:chunk_id,:owner_id,:source_type,:source_id,:term_key,:title,:content,
                    :content_hash,:embedding_model,:embedding_json,:updated_at)""", rows)


def search_study_memory(question: str, limit=5):
    question_low = (question or '').casefold()
    question_tokens = [s for s in re.findall(r'[A-Za-z0-9가-힣]+',question_low) if len(s)>1]
    ranked = []
    for r in get_learned_rows():
        names = json.loads(r['aliases_json']) + [r['term_name']]
        score = sum(4 for n in names if len(n.strip())>=2 and n.casefold() in question_low)
        score += sum(1 for t in question_tokens if t in r['simple_definition'].casefold())
        if score:
            ranked.append((score, r))
    ranked.sort(key=lambda x:x[0], reverse=True)
    return [r for _,r in ranked[:limit]]

# PharmaMate 2.2: 기존 DB를 보존하면서 학습 메모와 관련 질문·답변을 추가 저장합니다.
def initialize_study_notes():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS term_notes (
            term_key TEXT PRIMARY KEY,
            note TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS term_qa (
            qa_id TEXT PRIMARY KEY,
            term_key TEXT NOT NULL,
            article_id TEXT NOT NULL DEFAULT '',
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_term_qa_key ON term_qa(term_key,created_at);
        """)

def get_saved_note(term_key: str) -> str:
    with connect_db() as conn:
        row=conn.execute('SELECT note FROM term_notes WHERE term_key=?',(term_key,)).fetchone()
    return row['note'] if row else ''

def get_term_qa(term_key: str, limit: int = 15):
    with connect_db() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM term_qa WHERE term_key=? ORDER BY created_at DESC LIMIT ?',
            (term_key,limit))]

def related_qa_in_state(state: dict, term: dict):
    # 저장 시점에 선택된 용어와 실제로 연결되었다고 판정된 대화만 사용합니다.
    prev=get_saved_term(term)
    keys={normalize_term(x) for x in aliases_for(term)}
    if prev:
        keys.add(prev['term_key'])
    return [item for item in (state or {}).get('history',[]) if
            item.get('linked_term_key') in keys and item.get('question') and item.get('answer')]

def draft_learning_note(term: dict, state: dict) -> str:
    relevant=related_qa_in_state(state,term)
    lines=[f"## {term['term']}",
           f"- 분류: {term.get('category','기타')}",
           f"- 기본 개념: {term.get('simple_definition','')}",
           f"- 기사에서의 의미: {term.get('article_context','')}"]
    if relevant:
        lines += ['', '### 관련 질문·답변']
        for qa in relevant[-8:]:
            lines += [f"**Q.** {qa['question']}",f"**A.** {qa['answer'][:1600]}", '']
    return '\n'.join(lines)

def save_learning_bundle(term: dict, state: dict, user_note: str):
    # 기존 learned_terms/term_examples 로직을 재사용합니다.
    prev,key=save_term_card(term,state.get('article_id','') or '',state.get('url',''))
    relevant=related_qa_in_state(state,term)
    note=(user_note or '').strip() or draft_learning_note(term,state)
    with connect_db() as conn:
        conn.execute("""INSERT INTO term_notes(term_key,note,updated_at) VALUES (?,?,?)
            ON CONFLICT(term_key) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at""",
            (key,note,now_local()))
        inserted=0
        for item in relevant:
            # 같은 대화가 여러 번 저장되어도 중복 삽입하지 않습니다.
            data=(key+(item.get('article_id') or '')+item['question']+item['answer']).encode('utf-8')
            qa_id=hashlib.sha256(data).hexdigest()[:32]
            cur=conn.execute("""INSERT OR IGNORE INTO term_qa
                (qa_id,term_key,article_id,question,answer,created_at) VALUES(?,?,?,?,?,?)""",
                (qa_id,key,item.get('article_id') or '',item['question'],item['answer'],now_local()))
            inserted+=cur.rowcount
    return prev,key,inserted,len(relevant),note



def configure_database(data_dir: str | Path) -> Path:
    """DB 위치를 설정하고 현재 스키마를 생성합니다. 기존 행은 삭제하지 않습니다."""
    global DB_PATH
    data_dir = Path(data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    DB_PATH = data_dir / "pharmamate.sqlite3"
    initialize_database()
    initialize_study_notes()
    return DB_PATH
