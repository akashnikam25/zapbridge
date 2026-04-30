"""
conftest.py — set fake env vars before any app module is imported.
pydantic-settings reads env at import time, so these must be at module level.
"""
import os
from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/zapbridge_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
