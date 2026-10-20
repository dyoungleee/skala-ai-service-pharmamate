"""SQLite 학습 기록 저장소. 경로 설정 후 명시적으로 스키마를 초기화합니다."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import unicodedata
import uuid
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
    conn.execute("PRAGMA foreign_keys=ON")
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
        CREATE TABLE IF NOT EXISTS study_sessions (
            session_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            active_article_json TEXT NOT NULL DEFAULT '{}',
            selected_term_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_study_sessions_token_hash
            ON study_sessions(token_hash);
        CREATE TABLE IF NOT EXISTS session_turns (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            term_key TEXT NOT NULL DEFAULT '',
            term_name TEXT NOT NULL DEFAULT '',
            article_id TEXT NOT NULL DEFAULT '',
            related_to_selected INTEGER NOT NULL DEFAULT 0,
            route TEXT NOT NULL DEFAULT '',
            sources_json TEXT NOT NULL DEFAULT '[]',
            recommendations_json TEXT NOT NULL DEFAULT '[]',
            validation_status TEXT NOT NULL DEFAULT '',
            validation_retries INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES study_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_turns_history
            ON session_turns(session_id, created_at);
        CREATE TABLE IF NOT EXISTS session_learning_records (
            session_id TEXT NOT NULL,
            term_key TEXT NOT NULL,
            term_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            category TEXT NOT NULL DEFAULT '',
            simple_definition TEXT NOT NULL DEFAULT '',
            article_context TEXT NOT NULL DEFAULT '',
            article_id TEXT NOT NULL DEFAULT '',
            article_url TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(session_id, term_key),
            FOREIGN KEY(session_id) REFERENCES study_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS session_study_qa (
            qa_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            term_key TEXT NOT NULL,
            article_id TEXT NOT NULL DEFAULT '',
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES study_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_study_qa_scope
            ON session_study_qa(session_id, term_key, created_at);
        CREATE TABLE IF NOT EXISTS session_industry_issues (
            issue_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            issue_text TEXT NOT NULL DEFAULT '',
            entities_json TEXT NOT NULL DEFAULT '[]',
            event_type TEXT NOT NULL DEFAULT '',
            clinical_phase TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, issue_id),
            FOREIGN KEY(session_id) REFERENCES study_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_issues_scope
            ON session_industry_issues(session_id, updated_at);
        CREATE TABLE IF NOT EXISTS session_articles (
            session_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL DEFAULT '',
            normalized_title TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            article_text TEXT NOT NULL DEFAULT '',
            analysis_json TEXT NOT NULL DEFAULT '{}',
            issue_id TEXT,
            read_at TEXT NOT NULL,
            PRIMARY KEY(session_id, article_id),
            FOREIGN KEY(session_id) REFERENCES study_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY(session_id, issue_id) REFERENCES session_industry_issues(session_id, issue_id)
        );
        CREATE INDEX IF NOT EXISTS idx_session_articles_duplicates
            ON session_articles(session_id, canonical_url, content_hash, normalized_title);
        """)

def now_local():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def hash_session_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def create_study_session(session_id: str, token: str) -> None:
    timestamp = now_local()
    with connect_db() as conn:
        conn.execute("""INSERT INTO study_sessions
            (session_id,token_hash,created_at,updated_at) VALUES(?,?,?,?)""",
            (session_id, hash_session_token(token), timestamp, timestamp))


def session_exists(session_id: str) -> bool:
    with connect_db() as conn:
        return conn.execute(
            "SELECT 1 FROM study_sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None


def authenticate_study_session(session_id: str, token: str) -> bool:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT token_hash FROM study_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    if row is None or not token:
        return False
    return hmac.compare_digest(row["token_hash"], hash_session_token(token))


def session_id_for_access_token(token: str) -> str | None:
    """Resolve an opaque session bearer without storing or returning its plaintext."""
    if not token:
        return None
    token_hash = hash_session_token(token)
    with connect_db() as conn:
        row = conn.execute(
            "SELECT session_id,token_hash FROM study_sessions WHERE token_hash=? LIMIT 1",
            (token_hash,),
        ).fetchone()
    if row is None or not hmac.compare_digest(row["token_hash"], token_hash):
        return None
    return str(row["session_id"])


def get_study_session(session_id: str) -> dict | None:
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM study_sessions WHERE session_id=?", (session_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["active_article"] = json.loads(result.pop("active_article_json") or "{}")
    return result


def save_session_article(session_id: str, article: dict, selected_term_key: str = "") -> None:
    with connect_db() as conn:
        cur = conn.execute("""UPDATE study_sessions
            SET active_article_json=?, selected_term_key=?, updated_at=? WHERE session_id=?""",
            (json.dumps(article, ensure_ascii=False), selected_term_key, now_local(), session_id))
        if cur.rowcount != 1:
            raise KeyError("session not found")


def update_session_selected_term(session_id: str, selected_term_key: str) -> None:
    with connect_db() as conn:
        cur = conn.execute("""UPDATE study_sessions SET selected_term_key=?,updated_at=?
            WHERE session_id=?""", (selected_term_key, now_local(), session_id))
        if cur.rowcount != 1:
            raise KeyError("session not found")


def append_session_turn(session_id: str, turn: dict) -> None:
    created_at = datetime.now().astimezone().isoformat(timespec="microseconds")
    with connect_db() as conn:
        conn.execute("""INSERT INTO session_turns
            (turn_id,session_id,question,answer,term_key,term_name,article_id,related_to_selected,route,
             sources_json,recommendations_json,validation_status,validation_retries,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, session_id, turn["question"], turn["answer"],
             turn.get("term_key", ""), turn.get("term_name", ""), turn.get("article_id", ""),
             int(bool(turn.get("related_to_selected"))), turn.get("route", ""),
             json.dumps(turn.get("sources") or [], ensure_ascii=False),
             json.dumps(turn.get("recommendations") or [], ensure_ascii=False),
             turn.get("validation_status", ""), int(turn.get("validation_retries") or 0), created_at))
        conn.execute("""UPDATE study_sessions SET selected_term_key=?,updated_at=?
            WHERE session_id=?""", (turn.get("term_key", ""), created_at, session_id))


def get_session_turns(session_id: str, limit: int = 100) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute("""SELECT * FROM session_turns WHERE session_id=?
            ORDER BY created_at DESC, turn_id DESC LIMIT ?""", (session_id, max(0, min(limit, 200)))).fetchall()
    turns = []
    for row in reversed(rows):
        item = dict(row)
        item["related_to_selected"] = bool(item["related_to_selected"])
        item["sources"] = json.loads(item.pop("sources_json") or "[]")
        item["recommendations"] = json.loads(item.pop("recommendations_json") or "[]")
        turns.append(item)
    return turns


def save_session_study_record(session_id: str, term: dict, note: str = "") -> tuple[str, int, int]:
    term_key = normalize_term(term.get("term", ""))
    if not term_key:
        raise ValueError("저장할 용어가 없습니다.")
    timestamp = now_local()
    session = get_study_session(session_id)
    if session is None:
        raise KeyError("session not found")
    article = session.get("active_article") or {}
    article_id = str(article.get("article_id") or "")
    article_url = str(article.get("url") or "")
    aliases = aliases_for(term)
    with connect_db() as conn:
        conn.execute("""INSERT INTO session_learning_records
            (session_id,term_key,term_name,aliases_json,category,simple_definition,
             article_context,article_id,article_url,note,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id,term_key) DO UPDATE SET
                term_name=excluded.term_name,aliases_json=excluded.aliases_json,
                category=excluded.category,simple_definition=excluded.simple_definition,
                article_context=excluded.article_context,article_id=excluded.article_id,
                article_url=excluded.article_url,note=excluded.note,updated_at=excluded.updated_at""",
            (session_id, term_key, term.get("term", ""), json.dumps(aliases, ensure_ascii=False),
             term.get("category", ""), term.get("simple_definition", ""),
             term.get("article_context", ""), article_id, article_url, note, timestamp, timestamp))
        relevant = conn.execute("""SELECT question,answer,article_id FROM session_turns
            WHERE session_id=? AND term_key=? AND related_to_selected=1
            ORDER BY created_at""", (session_id, term_key)).fetchall()
        inserted = 0
        for item in relevant:
            qid = hashlib.sha256(
                f"{session_id}\0{term_key}\0{item['article_id']}\0{item['question']}\0{item['answer']}".encode("utf-8")
            ).hexdigest()[:32]
            cur = conn.execute("""INSERT OR IGNORE INTO session_study_qa
                (qa_id,session_id,term_key,article_id,question,answer,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (qid, session_id, term_key, item["article_id"], item["question"], item["answer"], timestamp))
            inserted += cur.rowcount
        conn.execute("UPDATE study_sessions SET updated_at=? WHERE session_id=?", (timestamp, session_id))
    return term_key, inserted, len(relevant)


def get_session_study_records(session_id: str) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute("""SELECT r.*,COUNT(q.qa_id) AS qa_count
            FROM session_learning_records r LEFT JOIN session_study_qa q
              ON q.session_id=r.session_id AND q.term_key=r.term_key
            WHERE r.session_id=? GROUP BY r.session_id,r.term_key
            ORDER BY r.updated_at DESC""", (session_id,)).fetchall()
    return [dict(row) for row in rows]


def _article_body_hash(article_text: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(article_text or "")).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _normalized_entities(values: list[str] | None) -> set[str]:
    return {
        re.sub(r"[^0-9a-z가-힣]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())
        for value in (values or [])
        if re.sub(r"[^0-9a-z가-힣]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())
    }


def _issue_tokens(value: str) -> set[str]:
    stop_words = {"제약", "바이오", "업계", "기업", "회사", "신약", "기술", "후보물질", "관련"}
    return {
        token for token in re.findall(r"[a-z0-9]+|[가-힣]+", unicodedata.normalize("NFKC", value or "").casefold())
        if len(token) > 1 and token not in stop_words
    }


def _issue_event_type(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    groups = (
        ("approval", ("허가", "승인", "인허가", "approval", "approved")),
        ("clinical", ("임상", "시험", "phase", "1상", "2상", "3상", "4상", "탑라인")),
        ("deal", ("기술이전", "라이선스", "라이센스", "파트너십", "협력", "계약", "licensing", "license", "collaboration")),
        ("investment", ("투자", "인수", "합병", "funding", "acquisition", "investment")),
        ("commercial", ("출시", "매출", "판매", "launch", "sales")),
        ("patent", ("특허", "patent")),
    )
    for name, markers in groups:
        if any(marker in text for marker in markers):
            return name
    return "other"


def _clinical_phase(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    match = re.search(r"(?:임상\s*)?([1-4]\s*상|phase\s*[1-4])", text)
    if not match:
        return ""
    phase = re.sub(r"\s+", "", match.group(1))
    return phase.replace("phase", "phase ") if phase.startswith("phase") else phase


def _same_industry_issue(issue_text: str, entities: list[str], event_type: str, phase: str,
                         candidate: dict) -> bool:
    new_entities = _normalized_entities(entities)
    saved_entities = _normalized_entities(json.loads(candidate.get("entities_json") or "[]"))
    shared_entities = new_entities & saved_entities
    if not shared_entities:
        return False
    new_phase = phase or _clinical_phase(issue_text)
    saved_phase = candidate.get("clinical_phase") or _clinical_phase(candidate.get("issue_text", ""))
    if new_phase != saved_phase and (new_phase or saved_phase):
        return False
    new_event = event_type or _issue_event_type(issue_text)
    saved_event = candidate.get("event_type") or _issue_event_type(candidate.get("issue_text", ""))
    if new_event != saved_event and new_event != "other" and saved_event != "other":
        return False
    normalized_new = normalize_article_title(issue_text)
    normalized_saved = normalize_article_title(candidate.get("issue_text", ""))
    if normalized_new and normalized_new == normalized_saved:
        return True
    if len(new_entities) > 1 and len(saved_entities) > 1 and len(shared_entities) < 2:
        return False
    new_tokens = _issue_tokens(issue_text)
    saved_tokens = _issue_tokens(candidate.get("issue_text", ""))
    if not new_tokens or not saved_tokens:
        return False
    containment = len(new_tokens & saved_tokens) / min(len(new_tokens), len(saved_tokens))
    return containment >= 0.75


def mark_session_article_read(session_id: str, article: dict, issue_id: str = "") -> dict:
    """Save one read article, dedupe exact copies, and conservatively group its issue."""
    if not session_exists(session_id):
        raise KeyError("session not found")
    analysis = article.get("analysis") or {}
    article_id = str(article.get("article_id") or "").strip()
    title = str(article.get("title") or "기사 원문").strip()
    source_url = str(article.get("url") or "").strip()
    article_text = str(article.get("article") or "")
    if not article_id or not analysis:
        raise ValueError("먼저 기사를 분석해 주세요.")
    source_key = canonical_article_url(source_url)
    title_key = normalize_article_title(title)
    body_hash = _article_body_hash(article_text)
    key_issue = str(analysis.get("key_issue") or "").strip()
    entities = [str(item).strip() for item in analysis.get("key_entities") or [] if str(item).strip()]
    event_type = _issue_event_type(key_issue)
    phase = _clinical_phase(key_issue)
    timestamp = now_local()

    with connect_db() as conn:
        existing_rows = conn.execute("""SELECT article_id,title,canonical_url,content_hash,
            issue_id FROM session_articles WHERE session_id=? ORDER BY read_at DESC""", (session_id,)).fetchall()
        duplicate = None
        duplicate_by = ""
        for row in existing_rows:
            if source_key and source_key == row["canonical_url"]:
                duplicate, duplicate_by = row, "url"
                break
            if body_hash and body_hash == row["content_hash"]:
                duplicate, duplicate_by = row, "content"
                break
            if title_key and title_key == normalize_article_title(row["title"]):
                duplicate, duplicate_by = row, "title"
                break
        if duplicate is not None:
            issue = conn.execute("""SELECT issue_id,title FROM session_industry_issues
                WHERE session_id=? AND issue_id=?""", (session_id, duplicate["issue_id"])).fetchone() \
                if duplicate["issue_id"] else None
            return {
                "article_id": duplicate["article_id"], "saved": False, "duplicate": True,
                "duplicate_by": duplicate_by,
                "issue_id": issue["issue_id"] if issue else None,
                "issue_title": issue["title"] if issue else "",
                "message": f"이미 읽은 기사로 저장되어 있습니다 ({duplicate_by}).",
            }

        if issue_id:
            selected_issue = conn.execute("""SELECT * FROM session_industry_issues
                WHERE session_id=? AND issue_id=?""", (session_id, issue_id)).fetchone()
            if selected_issue is None:
                raise ValueError("선택한 산업 이슈를 찾을 수 없습니다.")
            chosen_issue = dict(selected_issue)
            match_type = "manual"
        elif key_issue:
            candidates = conn.execute("""SELECT * FROM session_industry_issues
                WHERE session_id=? ORDER BY updated_at DESC""", (session_id,)).fetchall()
            chosen_issue = next((dict(row) for row in candidates if _same_industry_issue(
                key_issue, entities, event_type, phase, dict(row)
            )), None)
            match_type = "automatic" if chosen_issue else "new"
        else:
            chosen_issue = None
            match_type = "none"

        if key_issue and chosen_issue is None:
            new_issue_id = uuid.uuid4().hex
            conn.execute("""INSERT INTO session_industry_issues
                (issue_id,session_id,title,issue_text,entities_json,event_type,clinical_phase,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (new_issue_id, session_id, key_issue[:300], key_issue,
                 json.dumps(entities, ensure_ascii=False), event_type, phase, timestamp, timestamp))
            chosen_issue = {
                "issue_id": new_issue_id, "title": key_issue[:300], "issue_text": key_issue,
                "entities_json": json.dumps(entities, ensure_ascii=False), "event_type": event_type,
                "clinical_phase": phase,
            }
        elif chosen_issue is not None:
            prior_entities = json.loads(chosen_issue.get("entities_json") or "[]")
            merged_entities = list(dict.fromkeys(prior_entities + entities))
            conn.execute("""UPDATE session_industry_issues SET entities_json=?,updated_at=?
                WHERE session_id=? AND issue_id=?""",
                (json.dumps(merged_entities, ensure_ascii=False), timestamp, session_id, chosen_issue["issue_id"]))

        selected_issue_id = chosen_issue["issue_id"] if chosen_issue else None
        conn.execute("""INSERT INTO session_articles
            (session_id,article_id,title,source_url,canonical_url,normalized_title,content_hash,
             article_text,analysis_json,issue_id,read_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, article_id, title, source_url, source_key, title_key, body_hash,
             article_text, json.dumps(analysis, ensure_ascii=False), selected_issue_id, timestamp))
        conn.execute("UPDATE study_sessions SET updated_at=? WHERE session_id=?", (timestamp, session_id))
        issue_title = chosen_issue["title"] if chosen_issue else ""
        return {
            "article_id": article_id, "saved": True, "duplicate": False,
            "duplicate_by": "", "issue_id": selected_issue_id,
            "issue_title": issue_title, "match_type": match_type,
            "message": "기사를 읽은 기록에 저장했습니다." if not selected_issue_id
                else f"기사와 산업 이슈를 저장했습니다: {issue_title}",
        }


def get_session_articles(session_id: str, limit: int = 50) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute("""SELECT a.article_id,a.title,a.source_url,a.issue_id,
            i.title AS issue_title,a.read_at FROM session_articles a
            LEFT JOIN session_industry_issues i
              ON i.session_id=a.session_id AND i.issue_id=a.issue_id
            WHERE a.session_id=? ORDER BY a.read_at DESC LIMIT ?""",
            (session_id, max(1, min(limit, 200)))).fetchall()
    return [dict(row) for row in rows]


def get_session_industry_issues(session_id: str, limit: int = 50) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute("""SELECT i.*,
            (SELECT COUNT(*) FROM session_articles a
             WHERE a.session_id=i.session_id AND a.issue_id=i.issue_id) AS article_count
            FROM session_industry_issues i WHERE i.session_id=?
            ORDER BY i.updated_at DESC LIMIT ?""",
            (session_id, max(1, min(limit, 200)))).fetchall()
        issues = []
        for row in rows:
            issue = dict(row)
            issue["entities"] = json.loads(issue.pop("entities_json") or "[]")
            issue["articles"] = [dict(article) for article in conn.execute("""SELECT article_id,title,
                source_url,read_at FROM session_articles WHERE session_id=? AND issue_id=?
                ORDER BY read_at DESC""", (session_id, issue["issue_id"]))]
            issues.append(issue)
    return issues

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
        if not session_exists(owner_id):
            return []
        documents: list[dict] = []
        with connect_db() as conn:
            for row in conn.execute("""SELECT * FROM session_learning_records
                WHERE session_id=? ORDER BY updated_at DESC""", (owner_id,)):
                content = (
                    f"용어: {row['term_name']}\n분류: {row['category']}\n"
                    f"정의: {row['simple_definition']}\n별칭: {row['aliases_json']}\n"
                    f"기사 맥락: {row['article_context']}\n내 학습 메모: {row['note']}"
                )
                documents.append({
                    "owner_id": owner_id, "source_type": "session_note",
                    "source_id": row["term_key"], "record_id": f"session_note:{row['term_key']}",
                    "term_key": row["term_key"], "title": f"학습 메모: {row['term_name']}",
                    "content": content, "source_url": row["article_url"],
                })
            for row in conn.execute("""SELECT q.*,r.term_name FROM session_study_qa q
                JOIN session_learning_records r USING(session_id,term_key)
                WHERE q.session_id=? ORDER BY q.created_at DESC""", (owner_id,)):
                documents.append({
                    "owner_id": owner_id, "source_type": "session_qa",
                    "source_id": row["qa_id"], "record_id": f"session_qa:{row['qa_id']}",
                    "term_key": row["term_key"], "title": f"학습 Q&A: {row['term_name']}",
                    "content": f"질문: {row['question']}\n답변: {row['answer']}",
                    "source_url": "",
                })
            for row in conn.execute("""SELECT article_id,title,source_url,analysis_json
                FROM session_articles WHERE session_id=? ORDER BY read_at DESC""", (owner_id,)):
                analysis = json.loads(row["analysis_json"] or "{}")
                content = (
                    f"기사 제목: {row['title']}\n요약: {analysis.get('one_line_summary', '')}\n"
                    f"핵심 이슈: {analysis.get('key_issue', '')}\n"
                    f"주요 대상: {', '.join(analysis.get('key_entities') or [])}"
                )
                documents.append({
                    "owner_id": owner_id, "source_type": "session_article",
                    "source_id": row["article_id"], "record_id": f"session_article:{row['article_id']}",
                    "term_key": "", "title": f"읽은 기사: {row['title']}",
                    "content": content, "source_url": row["source_url"],
                })
        return [document for document in documents if document["content"].strip()]
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


def search_study_memory(question: str, limit=5, owner_id: str = "local"):
    question_low = (question or '').casefold()
    question_tokens = [s for s in re.findall(r'[A-Za-z0-9가-힣]+',question_low) if len(s)>1]
    if owner_id != "local":
        ranked_documents = []
        for document in get_memory_documents(owner_id):
            content = f"{document['title']}\n{document['content']}".casefold()
            score = sum(4 for token in question_tokens if token in content)
            if score:
                ranked_documents.append((score, document))
        ranked_documents.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in ranked_documents[:limit]]
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
