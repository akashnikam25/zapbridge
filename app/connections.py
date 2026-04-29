from redis import Redis
from rq import Queue
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)
queue = Queue("zapbridge", connection=redis_conn)

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
