"""프로젝트 경로와 환경 설정을 로드합니다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ProjectSettings:
    project_dir: Path
    env_file: Path
    openai_api_key: str
    model_name: str


def load_settings(project_dir: str | Path) -> ProjectSettings:
    root = Path(project_dir).expanduser().resolve()
    env_file = root / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.lower().startswith(("replace_", "your_", "여기에_")):
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. "
            f"{env_file} 파일을 만들고 OPENAI_API_KEY=... 를 입력한 뒤 이 셀을 다시 실행하세요."
        )

    model_name = os.getenv("PHARMAMATE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    return ProjectSettings(
        project_dir=root,
        env_file=env_file,
        openai_api_key=api_key,
        model_name=model_name,
    )
