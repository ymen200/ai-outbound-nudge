"""Settings for the Outreach Orchestrator service."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Outreach Orchestrator"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8002

    # Downstream module URLs
    SEQUENCE_GENERATOR_URL: str = "http://localhost:8001"
    MESSAGE_GENERATOR_URL: str = "http://localhost:8000"

    # Request timeouts (seconds)
    SEQUENCE_GENERATOR_TIMEOUT: int = 120
    MESSAGE_GENERATOR_TIMEOUT: int = 120
    OBSERVABILITY_TIMEOUT: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"

    # Debug mode — when true, both modules bypass memory reads/writes
    # for deterministic, repeatable test runs. Propagated to modules via config override.
    DEBUG_MODE: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
