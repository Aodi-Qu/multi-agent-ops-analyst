"""Application configuration via environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROJECT_NAME: str = "Multi-Agent Ops Analyst"
    VERSION: str = "0.1.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # SQLite
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./ops_analyst.db")

    # Chroma
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION", "ops_docs")

    # LLM (OpenAI-compatible, e.g. DeepSeek)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str | None = os.getenv("OPENAI_API_BASE", None)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
