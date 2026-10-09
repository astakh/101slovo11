from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # DB
    DATABASE_URL: str

    # Session
    SESSION_SECRET: str
    SESSION_TTL_DAYS: int = 30

    # GigaChat
    GIGACHAT_AUTH_KEY: str = ""
    GIGACHAT_SCOPE: str = "GIGACHAT_API_PERS"
    GIGACHAT_MODEL: str = "GigaChat"
    GIGACHAT_VERIFY_SSL: bool = False

    # LLM
    GEN_TEMPERATURE: float = 0.7
    EVAL_TEMPERATURE: float = 0.2
    LLM_LOG_RETENTION_DAYS: int = 90

    # Limits
    WORDS_PER_LESSON_DEFAULT: int = 5
    WORDS_PER_LESSON_MIN: int = 1
    WORDS_PER_LESSON_MAX: int = 10
    DAILY_LESSON_LIMIT_DEFAULT: int = 1
    DAILY_LESSON_LIMIT_MAX: int = 5

    # Dictionaries
    AVAILABLE_DICTIONARIES: List[str] = ["general", "it", "travel"]
    DEFAULT_DICTIONARY_CODE: str = "general"

    # Level
    MAX_LEVEL: str = "C2"

    ENV: str = "development"  # "production" или "development"

    # ============================================
    # Monetization (обязательные параметры)
    # ============================================

    # Freemium limits
    FREE_LESSON_PER_DAY_LIMIT: int
    FREE_LESSONS_TOTAL_LIMIT: int

    # Subscription pricing (в копейках)
    SUBSCRIPTION_MONTHLY_PRICE_KOP: int
    SUBSCRIPTION_6M_PRICE_KOP: int
    SUBSCRIPTION_6M_DISCOUNT_PERCENT: int

    # Grace period (для будущих рекуррентов)
    GRACE_PERIOD_DAYS: int

    # Referral
    REFERRAL_BONUS_DAYS: int
    REFERRAL_PROMO_MAX_ATTEMPTS: int

    # YooKassa
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""

    # Валидатор для парсинга строки через запятую в список
    @field_validator("AVAILABLE_DICTIONARIES", mode="before")
    @classmethod
    def parse_dictionaries(cls, v):
        if isinstance(v, str):
            return [d.strip() for d in v.split(",")]
        return v


settings = Settings()