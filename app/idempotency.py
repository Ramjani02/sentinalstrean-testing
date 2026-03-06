import redis
from app.config import REDIS_URL

r = redis.Redis.from_url(REDIS_URL)

def check_key(key: str):
    return r.get(key)

def store_key(key: str, value: str):
    r.setex(key, 86400, value)
