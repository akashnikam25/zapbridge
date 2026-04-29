from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SLACK_WEBHOOK_URL: str
    DATABASE_URL: str = "postgresql://localhost/zapbridge"
    REDIS_URL: str = "redis://localhost:6379"
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    FERNET_KEY: str
    ANTHROPIC_API_KEY: str
    GITHUB_WEBHOOK_SECRET: str

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
