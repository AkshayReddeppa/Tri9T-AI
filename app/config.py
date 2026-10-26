from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file's parent-parent (project root).
# Fixes the CWD-dependence bug: works no matter where `uvicorn` is started from.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_PATH), extra="ignore")

    database_url: str = "sqlite:///./tri9t.db"
    ocr_enabled: bool = False
    llm_provider: str = "groq"
    groq_api_key: str = ""          # MUST come from .env only
    llm_model: str = "openai/gpt-oss-20b"
    llm_max_attempts: int = 3
    data_raw_dir: str = "data/raw"
    generations_dir: str = "data/generations"
    fake_llm_script: list[str] = []

settings = Settings()