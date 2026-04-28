# Slice 9: Unit Test Suite

**Estimated time:** ~1.5 hours  
**Note:** Write these alongside the slice they cover, not all at once at the end.  
**Files created:** `pytest.ini`, `tests/test_validator.py`, `tests/test_idempotency.py`, `tests/test_processor.py`, `tests/test_tokens.py`, `tests/test_oauth_state.py`, `tests/test_github.py`

---

## `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
```

---

## `tests/test_validator.py` — covers Slice 2

```python
import pytest
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
```

---

## `tests/test_idempotency.py` — covers Slice 3

Uses `fakeredis` — no real Redis needed.

```python
import fakeredis
from app.webhooks.receiver import is_duplicate, IDEMPOTENCY_TTL

def test_first_delivery_not_duplicate(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.webhooks.receiver.redis_conn", r)
    assert is_duplicate("delivery-abc") is False

def test_second_delivery_is_duplicate(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.webhooks.receiver.redis_conn", r)
    is_duplicate("delivery-abc")
    assert is_duplicate("delivery-abc") is True

def test_ttl_is_set(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.webhooks.receiver.redis_conn", r)
    is_duplicate("delivery-xyz")
    ttl = r.ttl("webhook:delivery-xyz")
    assert 0 < ttl <= IDEMPOTENCY_TTL
```

---

## `tests/test_processor.py` — covers Slices 4 & 5

```python
import pytest
from unittest.mock import MagicMock, patch
from app.workers.processor import format_message, _summarize_event, build_prompt

def test_format_message():
    payload = {"repository": {"full_name": "user/repo"}, "action": "opened"}
    assert "user/repo" in format_message("pull_request", payload)
    assert "opened" in format_message("pull_request", payload)

def test_summarize_event_valid():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text="PR opened by Alice: adds login feature.")
    ]
    with patch("app.workers.processor.anthropic_client", mock_client):
        result = _summarize_event("pull_request", {})
    assert len(result) >= 10

def test_summarize_event_too_short():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="ok")]
    with patch("app.workers.processor.anthropic_client", mock_client):
        with pytest.raises(ValueError, match="unusable summary"):
            _summarize_event("pull_request", {})

def test_build_prompt_truncates_long_payload():
    import json
    long_payload = {"data": "x" * 3000}
    prompt = build_prompt("push", long_payload)
    raw = json.dumps(long_payload)
    assert raw[:2000] in prompt
    assert raw[2000:] not in prompt
```

---

## `tests/test_tokens.py` — covers Slice 6

```python
import pytest
from cryptography.fernet import InvalidToken
from app.auth.tokens import encrypt, decrypt

def test_encrypt_decrypt_roundtrip():
    original = "ghp_test_token_12345"
    assert decrypt(encrypt(original)) == original

def test_decrypt_invalid_raises():
    with pytest.raises(InvalidToken):
        decrypt("not-valid-ciphertext")
```

---

## `tests/test_oauth_state.py` — covers Slice 6 CSRF

```python
import fakeredis
from app.auth.oauth import store_oauth_state, consume_oauth_state

def test_valid_state_consumed(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.auth.oauth.redis_conn", r)
    store_oauth_state("state-abc")
    assert consume_oauth_state("state-abc") is True

def test_invalid_state_rejected(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.auth.oauth.redis_conn", r)
    assert consume_oauth_state("state-never-stored") is False

def test_state_is_consumed_once(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr("app.auth.oauth.redis_conn", r)
    store_oauth_state("state-xyz")
    consume_oauth_state("state-xyz")
    assert consume_oauth_state("state-xyz") is False  # second use rejected
```

---

## `tests/test_github.py` — covers Slice 7

```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from app.github import fetch_with_retry

def _mock_resp(status_code, json_data=None, headers=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or []
    m.headers = headers or {}
    return m

def test_200_returns_json():
    with patch("httpx.get", return_value=_mock_resp(200, [{"id": 1}])):
        result = fetch_with_retry("http://example.com", {})
    assert result == [{"id": 1}]

def test_401_raises():
    with patch("httpx.get", return_value=_mock_resp(401)):
        with pytest.raises(HTTPException) as exc:
            fetch_with_retry("http://example.com", {})
    assert exc.value.status_code == 401

def test_max_retries_exhausted():
    with patch("httpx.get", return_value=_mock_resp(429)), \
         patch("time.sleep"):
        with pytest.raises(HTTPException) as exc:
            fetch_with_retry("http://example.com", {}, max_retries=2)
    assert exc.value.status_code == 429
```

---

## Run all tests

```bash
pytest tests/ -v
```

Expected: 15 tests, all green, no external services hit.

---

## Interview story

"I have unit tests for every security-critical component: HMAC validation (3 cases), idempotency (3 cases), Claude output validation (2 cases), Fernet roundtrip (2 cases), OAuth CSRF state (3 cases), GitHub retry logic (3 cases). I use `fakeredis` to test Redis behavior without a real connection. No external services are hit during `pytest` — the whole suite runs offline."
