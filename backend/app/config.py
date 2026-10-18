from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    database_url: str = "sqlite:///./data/alexandria.db"
    checkpoint_url: str = "sqlite:///./data/checkpoints.db"
    data_dir: Path = Path("./data")
    redis_url: str = ""
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    ai_mode: str = "offline"
    openai_api_key: str = ""
    text_model: str = "gpt-4.1-mini"
    image_model: str = "gpt-image-1.5"
    economy_image_model: str = "gpt-image-1-mini"
    image_quality: str = "low"
    image_size: str = "1024x1536"
    max_image_references: int = 8
    max_reference_bytes: int = 8 * 1024 * 1024
    # Configure these from your provider's current pricing BEFORE enabling live mode.
    pricing_confirmed: bool = False
    input_usd_per_million: float = 1.0
    output_usd_per_million: float = 5.0
    preview_image_reservation_usd: float = 0.25
    final_image_reservation_usd: float = 1.0
    max_upload_bytes: int = 10 * 1024 * 1024
    jwt_secret: str = ""
    secure_cookies: bool = False
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.jwt_secret:
            # Retained locally across restarts; never sent to the browser or logged.
            import fcntl
            import os
            import secrets

            key_path = self.data_dir / ".session-key"
            fd = os.open(key_path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                value = f.read().strip()
                if not value:
                    value = secrets.token_hex(32)
                    f.write(value)
                    f.flush()
                self.jwt_secret = value
        return self


@lru_cache
def settings() -> Settings:
    return Settings().prepare()
