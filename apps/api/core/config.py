from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASE_DIR.parents[1]


def _csv(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(',') if x.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv('AEA_APP_NAME', 'API Evolution Assurance')
    environment: str = os.getenv('AEA_ENVIRONMENT', 'development')
    api_prefix: str = os.getenv('AEA_API_PREFIX', '/api/v1')
    data_dir: Path = Path(os.getenv('AEA_DATA_DIR', str(PROJECT_ROOT / 'data')))
    max_upload_bytes: int = int(os.getenv('AEA_MAX_UPLOAD_BYTES', str(80 * 1024 * 1024)))
    max_repo_file_bytes: int = int(os.getenv('AEA_MAX_REPO_FILE_BYTES', str(2 * 1024 * 1024)))
    max_repo_files: int = int(os.getenv('AEA_MAX_REPO_FILES', '5000'))
    execution_timeout_seconds: int = int(os.getenv('AEA_EXECUTION_TIMEOUT_SECONDS', '90'))
    cors_origins: tuple[str, ...] = tuple(_csv('AEA_CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173'))
    github_token: str = os.getenv('AEA_GITHUB_TOKEN', '')
    github_api_url: str = os.getenv('AEA_GITHUB_API_URL', 'https://api.github.com')
    github_api_version: str = os.getenv('AEA_GITHUB_API_VERSION', '2026-03-10')

    @property
    def db_path(self) -> Path:
        return self.data_dir / 'api_evolution.sqlite3'

    @property
    def repo_dir(self) -> Path:
        return self.data_dir / 'repositories'


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.repo_dir.mkdir(parents=True, exist_ok=True)
