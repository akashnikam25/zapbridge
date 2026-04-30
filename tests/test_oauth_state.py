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
