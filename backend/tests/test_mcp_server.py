from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from backend.app.db import repository
from backend.app.mcp_server import build_mcp_server, session_id_from_environment


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.previous_db_path = repository.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pharmamate-mcp-test-")
        repository.configure_database(self.temp_dir.name)
        self.session_a, self.token_a = "session-a", "synthetic-session-token-a"
        self.session_b, self.token_b = "session-b", "synthetic-session-token-b"
        repository.create_study_session(self.session_a, self.token_a)
        repository.create_study_session(self.session_b, self.token_b)
        repository.save_session_study_record(
            self.session_a,
            {"term": "항체-약물 접합체 (ADC)", "category": "Modality",
             "simple_definition": "항체가 약물을 표적 세포에 전달합니다."},
            "가상 A 세션의 학습 메모입니다.",
        )
        repository.save_session_study_record(
            self.session_b,
            {"term": "CAR-T", "category": "Modality",
             "simple_definition": "가상 B 세션의 세포치료 기록입니다."},
            "다른 세션의 비공개 메모입니다.",
        )
        repository.mark_session_article_read(self.session_a, {
            "article_id": "synthetic-article-a",
            "title": "가상 ADC 임상 결과 기사",
            "url": "https://example.invalid/adc-trial",
            "article": "가상 기사 본문입니다.",
            "analysis": {
                "key_issue": "가상 ADC 임상 2상 계획 발표",
                "key_entities": ["가상 ADC"],
            },
        })

    def tearDown(self):
        repository.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_session_bearer_lookup_returns_only_the_matching_session(self):
        self.assertEqual(repository.session_id_for_access_token(self.token_a), self.session_a)
        self.assertEqual(repository.session_id_for_access_token(self.token_b), self.session_b)
        self.assertIsNone(repository.session_id_for_access_token("unknown-token"))
        self.assertIsNone(repository.session_id_for_access_token(""))

    def test_invalid_or_missing_process_token_fails_before_server_start(self):
        with patch.dict(os.environ, {
            "PHARMAMATE_SESSION_TOKEN": "unknown-token",
            "PHARMAMATE_DATA_DIR": self.temp_dir.name,
        }):
            with self.assertRaisesRegex(RuntimeError, "유효한 세션 토큰"):
                session_id_from_environment()

    def test_mcp_exposes_tools_resource_prompt_and_scopes_results(self):
        server = build_mcp_server(lambda: self.session_a)

        async def exercise():
            async with Client(server) as client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                prompts = await client.list_prompts()
                self.assertEqual({tool.name for tool in tools.tools}, {
                    "search_learning_records", "search_read_articles",
                })
                for tool in tools.tools:
                    input_schema = json.dumps(tool.input_schema)
                    self.assertNotIn("session_id", input_schema)
                    self.assertNotIn("token", input_schema)
                self.assertEqual([resource.uri for resource in resources.resources], [
                    "pharmamate://learning-records",
                ])
                self.assertEqual([prompt.name for prompt in prompts.prompts], [
                    "explain_from_learning_records",
                ])
                found = await client.call_tool("search_learning_records", {
                    "query": "항체 약물 접합체",
                })
                payload = found.structured_content
                self.assertTrue(payload)
                self.assertIn("session_note:adc", json.dumps(payload, ensure_ascii=False))
                self.assertNotIn("다른 세션의 비공개 메모", json.dumps(payload, ensure_ascii=False))
                resource = await client.read_resource("pharmamate://learning-records")
                resource_text = resource.contents[0].text
                self.assertIn("가상 A 세션", resource_text)
                self.assertNotIn("다른 세션의 비공개 메모", resource_text)
                articles = await client.call_tool("search_read_articles", {"query": "ADC 임상"})
                self.assertIn("synthetic-article-a", json.dumps(articles.structured_content, ensure_ascii=False))
                prompt = await client.get_prompt("explain_from_learning_records", {
                    "question": "ADC는 어떻게 작동해?",
                })
                self.assertIn("search_learning_records", prompt.messages[0].content.text)

        asyncio.run(exercise())

    def test_stdio_transport_uses_process_token_to_scope_session(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.app.mcp_server"],
            env={
                "PHARMAMATE_SESSION_TOKEN": self.token_a,
                "PHARMAMATE_DATA_DIR": self.temp_dir.name,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            cwd=Path(__file__).resolve().parents[2],
        )

        async def exercise():
            async with Client(params) as client:
                result = await client.call_tool("search_learning_records", {
                    "query": "항체 약물 접합체",
                })
                payload = json.dumps(result.structured_content, ensure_ascii=False)
                self.assertIn("가상 A 세션", payload)
                self.assertNotIn("다른 세션의 비공개 메모", payload)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
