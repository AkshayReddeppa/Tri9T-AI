from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tri9t.db"
    ocr_enabled: bool = False
    llm_provider: str = "groq"
    groq_api_key: str = ""
    data_raw_dir: str = "data/raw"
    generations_dir: str = "data/generations"

settings = Settings()