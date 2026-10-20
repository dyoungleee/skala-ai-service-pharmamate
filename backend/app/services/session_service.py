"""High-entropy bearer credentials for anonymous, local study sessions."""
from __future__ import annotations

import secrets
import uuid

from backend.app.db import repository


def create_anonymous_session() -> tuple[str, str, str]:
    session_id = str(uuid.uuid4())
    access_token = secrets.token_urlsafe(32)
    repository.create_study_session(session_id, access_token)
    session = repository.get_study_session(session_id)
    assert session is not None
    return session_id, access_token, session["created_at"]


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return token.strip()


def can_access_session(session_id: str, authorization: str | None) -> bool:
    token = bearer_token(authorization)
    return repository.authenticate_study_session(session_id, token)
