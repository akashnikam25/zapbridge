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
