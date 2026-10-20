"""Synthetic comparison of PharmaMate 2.2 article dedupe and F7.2 grouping."""
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import repository


CASES = [
    {
        "case_id": "same_url_tracking_parameters",
        "expected_duplicate": True,
        "expected_same_issue": False,
        "first": {
            "article_id": "url-a", "title": "HB-101 임상 2상 주요 결과",
            "url": "https://news.example.org/story/1?utm_source=feed",
            "article": "synthetic article body one",
            "issue": "HB-101 임상 2상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
        "second": {
            "article_id": "url-b", "title": "HB-101 임상 2상 주요 결과",
            "url": "https://www.news.example.org/story/1?utm_source=mail",
            "article": "different body copy",
            "issue": "HB-101 임상 2상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
    },
    {
        "case_id": "same_body_mirrored_url",
        "expected_duplicate": True,
        "expected_same_issue": False,
        "first": {
            "article_id": "body-a", "title": "HB-101 임상 데이터",
            "url": "https://news.example.org/story/2", "article": "Mirror body for synthetic case",
            "issue": "HB-101 임상 2상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
        "second": {
            "article_id": "body-b", "title": "다른 매체의 다른 제목",
            "url": "https://mirror.example.org/copy", "article": "  MIRROR   BODY for synthetic case ",
            "issue": "HB-101 2상 임상 결과 공개", "entities": ["HanbitBio", "HB-101"],
        },
    },
    {
        "case_id": "same_trial_result_paraphrase",
        "expected_duplicate": False,
        "expected_same_issue": True,
        "first": {
            "article_id": "issue-a", "title": "HB-101 임상 2상 결과 발표",
            "url": "https://news.example.org/story/3", "article": "synthetic article body three",
            "issue": "HB-101 임상 2상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
        "second": {
            "article_id": "issue-b", "title": "HB-101 2상 임상 결과 공개",
            "url": "https://news.example.org/story/4", "article": "synthetic article body four",
            "issue": "HB-101 2상 임상 결과 공개", "entities": ["HanbitBio", "HB-101"],
        },
    },
    {
        "case_id": "same_candidate_different_phase",
        "expected_duplicate": False,
        "expected_same_issue": False,
        "first": {
            "article_id": "phase-a", "title": "HB-101 임상 2상 결과",
            "url": "https://news.example.org/story/5", "article": "synthetic phase two body",
            "issue": "HB-101 임상 2상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
        "second": {
            "article_id": "phase-b", "title": "HB-101 임상 3상 결과",
            "url": "https://news.example.org/story/6", "article": "synthetic phase three body",
            "issue": "HB-101 임상 3상 결과 발표", "entities": ["HanbitBio", "HB-101"],
        },
    },
    {
        "case_id": "same_company_different_candidate",
        "expected_duplicate": False,
        "expected_same_issue": False,
        "first": {
            "article_id": "candidate-a", "title": "HB-101 임상 2상 결과",
            "url": "https://news.example.org/story/7", "article": "synthetic candidate one",
            "issue": "HanbitBio HB-101 clinical phase 2 results", "entities": ["HanbitBio", "HB-101"],
        },
        "second": {
            "article_id": "candidate-b", "title": "HB-202 임상 2상 결과",
            "url": "https://news.example.org/story/8", "article": "synthetic candidate two",
            "issue": "HanbitBio HB-202 clinical phase 2 results", "entities": ["HanbitBio", "HB-202"],
        },
    },
]


def as_article(row: dict) -> dict:
    return {
        "article_id": row["article_id"], "title": row["title"], "url": row["url"],
        "article": row["article"],
        "analysis": {
            "article_type": "임상", "one_line_summary": "synthetic fixture",
            "key_issue": row["issue"], "key_entities": row["entities"],
            "key_terms": [], "confusing_points": [],
        },
    }


def run() -> list[dict]:
    original_db_path = repository.DB_PATH
    results = []
    try:
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix="pharmamate-issue-eval-") as temp_dir:
                repository.configure_database(Path(temp_dir))
                legacy_first = repository.save_read_article({**as_article(case["first"]), "analysis": as_article(case["first"])["analysis"]})
                legacy_second = repository.save_read_article({**as_article(case["second"]), "analysis": as_article(case["second"])["analysis"]})

                session_id = str(uuid.uuid4())
                repository.create_study_session(session_id, "synthetic-test-token")
                candidate_first = repository.mark_session_article_read(session_id, as_article(case["first"]))
                candidate_second = repository.mark_session_article_read(session_id, as_article(case["second"]))
                results.append({
                    "case_id": case["case_id"],
                    "expected_duplicate": case["expected_duplicate"],
                    "baseline_duplicate": not legacy_second,
                    "candidate_duplicate": candidate_second["duplicate"],
                    "duplicate_by": candidate_second["duplicate_by"],
                    "expected_same_issue": case["expected_same_issue"],
                    "baseline_same_issue": False,
                    "candidate_same_issue": bool(not candidate_second["duplicate"] and candidate_first["issue_id"] and
                        candidate_first["issue_id"] == candidate_second["issue_id"]),
                    "candidate_match_type": candidate_second.get("match_type", "duplicate"),
                })
    finally:
        repository.DB_PATH = original_db_path
    return results


def metrics(results: list[dict], expected_key: str, actual_key: str) -> dict[str, float | int | None]:
    tp = sum(row[expected_key] and row[actual_key] for row in results)
    fp = sum(not row[expected_key] and row[actual_key] for row in results)
    fn = sum(row[expected_key] and not row[actual_key] for row in results)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
    }


if __name__ == "__main__":
    output = run()
    issue_cases = [row for row in output if not row["expected_duplicate"]]
    print(json.dumps({
        "cases": output,
        "baseline_duplicate_metrics": metrics(output, "expected_duplicate", "baseline_duplicate"),
        "candidate_duplicate_metrics": metrics(output, "expected_duplicate", "candidate_duplicate"),
        "baseline_issue_link_metrics": metrics(issue_cases, "expected_same_issue", "baseline_same_issue"),
        "candidate_issue_link_metrics": metrics(issue_cases, "expected_same_issue", "candidate_same_issue"),
    }, ensure_ascii=False, indent=2))
