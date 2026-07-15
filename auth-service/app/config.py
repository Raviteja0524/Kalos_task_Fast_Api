from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# auth-service/.env — resolved from this file's location so it works from any CWD


class Settings(BaseSettings):
    DATABASE_URL: str  # no default = required; validated at startup
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
