import logging
import os
from pydantic_settings import BaseSettings
from typing import Optional

_log = logging.getLogger(__name__)

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Agentic Outreach API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Google Gemini
    GOOGLE_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_FALLBACK_MODEL: str = "models/gemma-3-27b-it"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_TOKENS: int = 2048
    
    # Redis
    REDIS_URL: Optional[str] = None           # e.g. redis://localhost:6379/0 — leave empty to use in-memory fallback

    # Research Tools
    USE_MOCK_DATA: bool = True
    LINKEDIN_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None
    CRM_DATABASE_URL: Optional[str] = None
    
    # Validation
    MIN_QUALITY_SCORE: int = 80
    MAX_ITERATIONS: int = 3
    
    # Features
    ENABLE_HUMAN_REVIEW: bool = False
    ENABLE_AUTO_SEND: bool = False
    ENABLE_LEARNING_LOOP: bool = False
    
    # Debug Mode
    # When True: memory is bypassed (no reads, no writes) and a /api/memory/flush
    # endpoint is available to wipe all stored data. Use during development/testing
    # to get deterministic results without accumulated memory pollution.
    # When False (production): memory is fully active.
    DEBUG_MODE: bool = True

    # Gmail SMTP (free email sending)
    GMAIL_ADDRESS: Optional[str] = None
    GMAIL_APP_PASSWORD: Optional[str] = None

    # Unipile (LinkedIn sending)
    UNIPILE_API_KEY: Optional[str] = None
    UNIPILE_DSN: Optional[str] = None          # e.g. "api4.unipile.com:13465"
    UNIPILE_DEFAULT_ACCOUNT_ID: Optional[str] = None  # your connected LinkedIn account ID
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "app.log"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()

# Warn about env vars that look like typos of known settings fields.
# extra="ignore" prevents hard errors but we still want visibility.
_known_upper = {f.alias if hasattr(f, 'alias') and f.alias else name
                for name, f in Settings.model_fields.items()}
for _key in sorted(os.environ):
    if _key.isupper() and _key not in _known_upper and not _key.startswith(("_", "PYTEST_", "HOME", "PATH", "SYSTEM", "COMSPEC", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USER", "HOSTNAME", "PWD", "SHLVL", "WINDIR", "PROGRAM", "COMMONPROGRAM", "NUMBER_OF_PROCESSORS", "PROCESSOR_", "OS", "PATHEXT", "PSMODULEPATH", "SESSIONNAME", "LOGONSERVER", "HOMEDRIVE", "HOMEPATH", "DRIVERDATA", "OneDrive", "PUBLIC", "ALLUSERSPROFILE", "ProgramData", "ProgramW6432")):
        _log.warning("Unrecognised env var '%s' — ignored by Settings (possible typo?)", _key)