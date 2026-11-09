"""
app/config.py — centralised settings loaded from environment / .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Google Gemini
    gemini_api_key: str = ""

    # ChromaDB
    chroma_persist_dir: str = "./data/vector_db"

    # Persona
    persona_name: str = "TargetFriendName"
    persona_profile_path: str = "./data/persona_profile.json"

    # Server
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
