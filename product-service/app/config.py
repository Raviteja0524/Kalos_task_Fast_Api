from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# product-service/.env — resolved from this file's location so it works from any CWD
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str  # no default = required; validated at startup
    REDIS_URL: str = "redis://localhost:6379/0"
    # Shared with the Auth Service — this is how tokens are verified without
    # any call to the auth DB
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ENVIRONMENT: str = "development"
    PRODUCT_CACHE_TTL_SECONDS: int = 300  # spec: 5 minutes

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")


settings = Settings()
