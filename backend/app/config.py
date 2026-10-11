"""Application settings, read only from environment variables (or a local .env)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"
MIN_PRODUCTION_SECRET_LENGTH = 32

HUMAN_REVIEW_NOTICE = (
    "Clinical decision support only. This assessment supports, and does not replace, "
    "review by a qualified clinician or trial investigator. Final eligibility must be "
    "confirmed by the study team."
)


class Settings(BaseSettings):
    # The repo-root .env (shared with docker compose) is read first; backend/.env overrides it.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("./data")
    # PostgreSQL holds all records when set (e.g. postgresql://user:pass@host:5432/db); otherwise the
    # JSON file store under DATA_DIR is used. Uploaded PDFs and retrieval indexes stay under DATA_DIR.
    database_url: str | None = None
    # Redis holds live workflow state (per-agent progress and outputs) when set; otherwise in-process memory.
    redis_url: str | None = None
    run_state_ttl_seconds: int = 86400

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    llm_provider: Literal["gemini", "anthropic", "openai", "none"] = "none"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 60.0

    embeddings_enabled: bool = True
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Optional clinical NLP: a BioBERT sentence model that flags possible matches between a criterion's
    # condition and differently worded patient diagnoses. It only adds review notes, never decides.
    clinical_nlp_enabled: bool = False
    clinical_nlp_model: str = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
    clinical_nlp_threshold: float = 0.75

    # Optional web search for external context on ambiguous criteria. Only protocol wording is sent,
    # never patient data, and results are shown as references, never used in the decision.
    web_search_provider: Literal["tavily", "none"] = "none"
    web_search_api_key: str | None = None
    web_search_max_queries: int = 3

    frontend_origin: str = "http://localhost:5173"
    frontend_origin_regex: str | None = None  # e.g. Vercel preview URLs: https://cte-system(-[a-z0-9-]+)?\.vercel\.app
    max_upload_mb: int = 20
    stale_days: int = 90
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if not self.jwt_secret and self.app_env != "production":
            self.jwt_secret = DEV_JWT_SECRET  # blank JWT_SECRET= in a dev .env
        if self.app_env == "production" and (
            self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < MIN_PRODUCTION_SECRET_LENGTH
        ):
            raise ValueError(
                f"JWT_SECRET must be a random string of at least {MIN_PRODUCTION_SECRET_LENGTH} "
                "characters when APP_ENV=production"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def web_search_enabled(self) -> bool:
        return self.web_search_provider != "none" and bool(self.web_search_api_key)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def store_dir(self) -> Path:
        return self.data_dir / "store"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"


@lru_cache
def get_settings() -> Settings:
    return Settings()
