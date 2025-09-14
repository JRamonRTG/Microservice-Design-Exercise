
import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from observability_asgi import (
    init_logging, CorrelationIdASGIMiddleware, RequestLoggingASGIMiddleware,
    set_correlation_id
)
from redis_client import get_client, STREAM_IN
from models import Notification

logger = init_logging(os.getenv("SERVICE_NAME", "notification-service"))
app = FastAPI(title="Notification Service")

# Middlewares ASGI (más robustos)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequestLoggingASGIMiddleware, logger=logger)
app.add_middleware(CorrelationIdASGIMiddleware, header_name="x-correlation-id")

# Redis
r = get_client()
GROUP = os.getenv("NOTIF_GROUP", "notification_group")
CONSUMER = os.getenv("NOTIF_CONSUMER", "notification_consumer_1")

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
            resp = r.xreadgroup(groupname=GROUP, consumername=CONSUMER, streams=last, count=10, block=2000)
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

                        if payload.get("event") == "PaymentProcessed":
                            n = Notification(
                                id=len(notifications) + 1,
                                user_id=int(payload.get("user_id", 0)),
                                message=f"Pago {payload.get('payment_id')} de usuario {payload.get('user_id')} -> {payload.get('status')} (monto {payload.get('amount')})",
                                created_at=datetime.now(timezone.utc),
                                correlation_id=cid
                            )
                            notifications.append(n.model_dump())
                            logger.info("notification_stored", extra={"extra": {"event": "notification_stored", "payload": payload}})
                        r.xack(STREAM_IN, GROUP, msg_id)
                    except Exception as e:
                        logger.error(f"consume error: {e}", exc_info=True)
        except Exception as loop_err:
            logger.error(f"consumer_loop error: {loop_err}", exc_info=True)
            await asyncio.sleep(1.0)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(consume())

@app.get("/live")
def live():
    return {"ok": True, "service": "notification-service"}

@app.get("/health")
def health():
    try:
        r.ping()
        return {"status": "healthy", "service": "notification-service"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/notifications")
def get_notifications():
    return notifications
