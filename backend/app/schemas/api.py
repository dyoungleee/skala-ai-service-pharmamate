"""Request and response models for the local PharmaMate API."""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.schemas.article import ArticleAnalysis, PharmaTerm
from backend.app.services.recommendations import LearningQuestion


class ArticleAnalyzeRequest(BaseModel):
    url: str = Field(default="", max_length=2048)
    pasted_text: str = Field(default="", max_length=100_000)
    title: str = Field(default="", max_length=300)


class ArticleAnalyzeResponse(BaseModel):
    article_id: str
    article: str
    url: str
    title: str
    load_method: str
    analysis: ArticleAnalysis


class ChatHistoryItem(BaseModel):
    question: str = Field(max_length=1000)
    answer: str = Field(max_length=6000)
    linked_to_selected: bool = False


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    article: str = Field(default="", max_length=14_000)
    term: str = Field(default="", max_length=1500)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=12)


class ChatResponse(BaseModel):
    answer: str
    route: str = ""
    related_to_selected: bool = False
    sources: list[dict[str, str]] = Field(default_factory=list)
    validation_status: str = ""
    validation_retries: int = 0
    recommendations: list[LearningQuestion] = Field(default_factory=list)


class SaveStudyRecordRequest(BaseModel):
    term: PharmaTerm
    article_id: str = Field(min_length=1, max_length=100)
    article_url: str = Field(default="", max_length=2048)
    note: str = Field(default="", max_length=8000)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=20)


class SaveStudyRecordResponse(BaseModel):
    term_key: str
    new_questions: int
    matched_questions: int
    message: str


class StudyRecordSummary(BaseModel):
    term_key: str
    term_name: str
    category: str
    simple_definition: str
    review_count: int
    first_learned_at: str
