from app.connections import redis_conn

IDEMPOTENCY_TTL = 86400  # 24 hours


def is_duplicate(delivery_id: str) -> bool:
    key = f"webhook:{delivery_id}"
    # SET NX EX is fully atomic: set-if-not-exists + expiry in one round-trip.
    # SETNX + EXPIRE is NOT atomic — if the process dies between them, the key
    # has no TTL and that delivery ID is locked out forever (memory leak + permanent block).
    already_seen = not redis_conn.set(key, 1, nx=True, ex=IDEMPOTENCY_TTL)
    return already_seen
