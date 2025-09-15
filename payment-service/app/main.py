# payment-service/app/main.py
import os, json, asyncio, logging
import redis
from fastapi import FastAPI
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.observability import init_logging, CorrelationIdMiddleware, RequestLoggingMiddleware, set_correlation_id
from app.database import init_db, get_session_local, engine
from app.routers.payment import router as payment_router
from app.services.payment_service import payment_service
from app.redis_client import get_client, STREAM_IN, STREAM_OUT
from app.resilience import get_snapshot

logger = init_logging(os.getenv("SERVICE_NAME","payment-service"))
app = FastAPI(title="Payment Service")

app.add_middleware(CorrelationIdMiddleware, header_name="x-correlation-id")
app.add_middleware(RequestLoggingMiddleware, logger=logger)

r = get_client()
GROUP = os.getenv("PAYMENT_GROUP", "payment_group")
CONSUMER = os.getenv("PAYMENT_CONSUMER", "payment_consumer_1")

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

async def consume_user_events():
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

                        if payload.get("event") == "PlanSelected":
                            user_id = int(payload["user_id"])
                            plan_id = int(payload["plan_id"])
                            logger.info("consume_plan_selected", extra={"extra": {
                                "event": "consume_plan_selected",
                                "stream": stream, "msg_id": msg_id,
                                "user_id": user_id, "plan_id": plan_id,
                                "correlation_id": cid
                            }})
                            session: Session = get_session_local()
                            try:
                                pay = payment_service.create_payment(session, user_id=user_id, plan_id=plan_id)
                                payment_service.process_payment(session, pay)
                            finally:
                                session.close()
                        r.xack(STREAM_IN, GROUP, msg_id)
                    except Exception as e:
                        logger.error(f"consume_user_events error: {e}", exc_info=True)
        except Exception as loop_err:
            logger.error(f"consumer_loop error: {loop_err}", exc_info=True)
            await asyncio.sleep(1.0)

@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(consume_user_events())

@app.get("/health")
def health():
    try:
        r.ping()
        return {"status": "healthy", "service": "payment-service"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/resilience")
def resilience():
    """Tablero simple de resiliencia (in-memory)."""
    return {
        "service": "payment-service",
        "redis_stream_out": STREAM_OUT,
        "snapshot": get_snapshot(),
    }

@app.get("/diag")
def diag():
    """Chequeos rápidos de dependencias + snapshot."""
    db_ok, redis_ok = True, True
    db_err, redis_err = None, None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_ok, db_err = False, str(e)
    try:
        get_client().ping()
    except Exception as e:
        redis_ok, redis_err = False, str(e)
    return {
        "service": "payment-service",
        "dependencies": {
            "db_ok": db_ok, "db_error": db_err,
            "redis_ok": redis_ok, "redis_error": redis_err,
        },
        "snapshot": get_snapshot(),
    }

# API
app.include_router(payment_router)
