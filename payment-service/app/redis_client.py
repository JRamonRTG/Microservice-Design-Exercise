import os
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"

STREAM_IN = os.getenv("USER_STREAM", "user_events")
STREAM_OUT = os.getenv("PAYMENT_STREAM", "payment_events")

# Timeouts (env-configurables)
REDIS_CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2"))  # segundos
REDIS_SOCKET_TIMEOUT  = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))   # segundos

_client = None

def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            ssl=REDIS_SSL,
            decode_responses=True,
            # ⏱️ timeouts
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            retry_on_timeout=True,
        )
    return _client
