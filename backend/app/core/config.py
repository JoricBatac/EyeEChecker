from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# All patient data must stay in Singapore (PRD 11, A.2).
REQUIRED_STORAGE_REGION = "asia-southeast1"
_DEV_SECRETS = {"change-me", "dev-only-secret", "dev-only-salt", "dev-only-change-me", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "development"  # development | test | production
    database_url: str = f"sqlite:///{(REPO_ROOT / 'scanassist.db').as_posix()}"

    storage_backend: str = "local"  # local | s3
    storage_bucket: str = "scanassist-photos"
    storage_region: str = REQUIRED_STORAGE_REGION
    storage_endpoint_url: str | None = None
    # Endpoint used inside signed URLs when clients reach storage on a different host (e.g. MinIO in Docker).
    storage_public_endpoint_url: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    local_storage_dir: Path = REPO_ROOT / ".local_storage"
    signed_url_ttl_seconds: int = 300
    photo_draft_ttl_hours: int = 72
    photo_job_interval_minutes: int = 15

    packs_dir: Path = REPO_ROOT / "packs"
    model_dir: Path = REPO_ROOT / "models"
    classifier: str | None = None  # overrides the pack's model kind: stub | zero_shot | onnx | none
    medsiglip_model_id: str = "google/medsiglip-448"
    hf_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HF_TOKEN", "HUGGINGFFACE_ACCESSTOKEN", "HUGGINGFACE_ACCESSTOKEN"),
    )

    llm_provider: str = "none"  # none | medgemma_selfhosted
    llm_base_url: str | None = None
    llm_model: str = "google/medgemma-4b-it"
    llm_timeout_ms: int = 8000

    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 12 * 60
    mfa_token_minutes: int = 5
    patient_hash_salt: str = "dev-only-salt"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8081", "http://localhost:19006"]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_runtime(self) -> None:
        """Refuse to start production with unsafe settings."""
        if not self.is_production:
            return
        problems = []
        if self.storage_region != REQUIRED_STORAGE_REGION:
            problems.append(f"STORAGE_REGION must be {REQUIRED_STORAGE_REGION}, got {self.storage_region!r}")
        if self.storage_backend != "s3":
            problems.append("STORAGE_BACKEND must be s3 in production")
        if self.jwt_secret in _DEV_SECRETS or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
        if self.patient_hash_salt in _DEV_SECRETS:
            problems.append("PATIENT_HASH_SALT must be set")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point to Postgres in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
