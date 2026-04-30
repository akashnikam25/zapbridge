import hmac
import hashlib
from app.webhooks.validator import validate_signature

SECRET = "test-secret"


def _sig(payload: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature():
    payload = b'{"action":"opened"}'
    assert validate_signature(payload, _sig(payload), SECRET) is True


def test_invalid_signature():
    assert validate_signature(b"payload", "sha256=deadbeef", SECRET) is False


def test_missing_prefix():
    assert validate_signature(b"payload", "md5=something", SECRET) is False
