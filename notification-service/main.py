import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis
import httpx

# Usa tu módulo de observabilidad actual (ASGI o BaseHTTP)
# from observability import init_logging, CorrelationIdMiddleware, RequestLoggingMiddleware, set_correlation_id
from observability_asgi import (
    init_logging, CorrelationIdASGIMiddleware, RequestLoggingASGIMiddleware, set_correlation_id
)

from redis_client import get_client, STREAM_IN
from models import Notification
from resilience import get_snapshot, record_consume_success, record_consume_failure

logger = init_logging(os.getenv("SERVICE_NAME", "notification-service"))
app = FastAPI(title="Notification Service")

# Middlewares
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequestLoggingASGIMiddleware, logger=logger)
app.add_middleware(CorrelationIdASGIMiddleware, header_name="x-correlation-id")

# Redis
r = get_client()
GROUP = os.getenv("NOTIF_GROUP", "notification_group")
CONSUMER = os.getenv("NOTIF_CONSUMER", "notification_consumer_1")

# URL del payment-service para /diag (timeout corto)
PAYMENT_HEALTH_URL = os.getenv("PAYMENT_HEALTH_URL", "http://payment-service:8002/health")
PAYMENT_HTTP_TIMEOUT = float(os.getenv("PAYMENT_HTTP_TIMEOUT", "2"))  # segundos

notifications: List[Dict[str, Any]] = []

def ensure_group():
    try:
        if not r.exists(STREAM_IN):
            r.xadd(STREAM_IN, {"data": "{}"})
        r.xgroup_create(STREAM_IN, GROUP, id="$", mkstream=True)
        logger.info("redis_group_created", extra={"extra": {"event": "redis_group_created", "stream": STREAM_IN, "group": GROUP}})
    except Exception as e:
        if "BUSYGROUP" in str(e):
            logger.info("redis_group_exists", extra={"extra": {"event": "redis_group_exists", "stream": STREAM_IN, "group": GROUP}})
        else:
            logger.error(f"ensure_group error: {e}", exc_info=True)

async def consume():
    ensure_group()
    last = {STREAM_IN: ">"}
    while True:
        try:
            resp = r.xreadgroup(groupname=GROUP, consumername=CONSUMER,
                                streams=last, count=10, block=2000)
            if not resp:
                await asyncio.sleep(0.2)
                continue

            for stream, messages in resp:
                for msg_id, fields in messages:
                    try:
                        raw = fields.get("data") or "{}"
                        payload = json.loads(raw)
                        cid = payload.get("correlation_id")
                        set_correlation_id(cid)

                        if payload.get("event") == "PaymentProcessed" or (
                            "payment_id" in payload and "user_id" in payload and payload.get("status") == "completed"
                        ):
                            # ... guardar notificación ...
                            record_consume_success(cid)

                        r.xack(STREAM_IN, GROUP, msg_id)
                    except Exception as e:
                        record_consume_failure(e, cid if 'cid' in locals() else None)
                        logger.error(f"consume error: {e}", exc_info=True)

        except redis.exceptions.TimeoutError:
            #  Poll idle: NO lo cuentes como fallo
            await asyncio.sleep(0.2)
            continue

        except (redis.exceptions.ConnectionError) as loop_err:
            #  esto sí es fallo real de dependencia
            record_consume_failure(loop_err, None)
            logger.warning(f"consumer_loop redis error: {loop_err}")
            await asyncio.sleep(1.0)

        except Exception as loop_err:
            logger.error(f"consumer_loop error: {loop_err}", exc_info=True)
            await asyncio.sleep(1.0)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(consume())

@app.get("/notifications")
def get_notifications():
    return notifications

@app.get("/health")
def health():
    try:
        r.ping()  # usa los timeouts configurados en el cliente
        return {"status": "healthy", "service": "notification-service"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/resilience")
def resilience_snapshot():
    """Tablero in-memory con contadores y últimos eventos del consumer."""
    return {
        "service": "notification-service",
        "redis_stream_in": STREAM_IN,
        "snapshot": get_snapshot(),
    }

@app.get("/diag")
async def diag():
    """Chequea Redis y Payment con timeouts cortos; devuelve snapshot."""
    redis_ok, payment_ok = True, True
    redis_err, payment_err = None, None

    # Redis: simple ping (ya con timeouts del cliente)
    try:
        r.ping()
    except Exception as e:
        redis_ok, redis_err = False, str(e)

    # Payment-service: health HTTP con timeout 2s
    try:
        async with httpx.AsyncClient(timeout=PAYMENT_HTTP_TIMEOUT) as client:
            resp = await client.get(PAYMENT_HEALTH_URL)
            payment_ok = resp.status_code == 200
            if not payment_ok:
                payment_err = f"status={resp.status_code}, body={resp.text[:200]}"
    except Exception as e:
        payment_ok, payment_err = False, str(e)

    return {
        "service": "notification-service",
        "dependencies": {
            "redis_ok": redis_ok, "redis_error": redis_err,
            "payment_ok": payment_ok, "payment_error": payment_err,
            "payment_health_url": PAYMENT_HEALTH_URL,
        },
        "snapshot": get_snapshot(),
    }

@app.get("/live")
def live():
    return {"ok": True, "service": "notification-service"}
