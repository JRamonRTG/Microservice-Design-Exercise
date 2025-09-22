import os
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Observabilidad
from observability_asgi import (
    init_logging,
    CorrelationIdASGIMiddleware,
    RequestLoggingASGIMiddleware,
)

# Redis sync centralizado + stream
from redis_client import get_client, STREAM_IN

# Resiliencia (métricas/snapshot)
from resilience import get_snapshot, record_consume_success, record_consume_failure

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
PAYMENT_HEALTH_URL = os.getenv("PAYMENT_HEALTH_URL", "http://payment-service:8002/health")

# ---- Estado compartido en memoria ----
NOTIFICATIONS: deque = deque(maxlen=1000)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_group(r, stream: str, group: str):
    try:
        r.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
    except Exception:
        # Grupo ya existe
        pass

def _parse_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    # Mensajes vienen como: {'data': '<json string>'}
    payload: Dict[str, Any] = {}
    data = fields.get("data")
    if isinstance(data, str):
        try:
            payload = json.loads(data)
        except Exception:
            payload = {"raw": data}
    # Conserva otros campos flat si existieran
    for k, v in fields.items():
        payload.setdefault(k, v)
    return payload

def _consumer_loop():
    r = get_client()
    stream = STREAM_IN
    group = os.getenv("NOTIF_GROUP", "notification_group")
    consumer_name = os.getenv("NOTIF_CONSUMER", f"notif-{os.getpid()}")

    _ensure_group(r, stream, group)

    while True:
        try:
            # Espera hasta 2000ms por mensajes nuevos
            resp = r.xreadgroup(
                groupname=group,
                consumername=consumer_name,
                streams={stream: '>'},
                count=32,
                block=2000
            )
            if not resp:
                continue

            for _, entries in resp:
                for msg_id, fields in entries:
                    try:
                        payload = _parse_fields(fields)

                        # Ignorar vacíos
                        if not payload or payload == {}:
                            r.xack(stream, group, msg_id)
                            continue

                        # Solo procesamos PaymentProcessed
                        if payload.get("event") != "PaymentProcessed":
                            r.xack(stream, group, msg_id)
                            continue

                        user_id = int(payload.get("user_id", 0))
                        status  = str(payload.get("status", "unknown"))
                        amount  = float(payload.get("amount", 0.0))
                        txid    = payload.get("transaction_id")
                        ts      = payload.get("created_at") or payload.get("timestamp") or _now_iso()
                        corr    = payload.get("correlation_id")

                        notif = {
                            "id": f"{int(time.time()*1000)}-{msg_id}",
                            "user_id": user_id,
                            "message": f"Pago {status} por {amount:.2f}",
                            "status": status,
                            "amount": amount,
                            "transaction_id": txid,
                            "created_at": ts,
                            "correlation_id": corr,
                            "payment_id": payload.get("payment_id"),
                        }

                        # Guardar en la misma estructura que lee el endpoint
                        NOTIFICATIONS.appendleft(notif)

                        # ACK solo después de agregar
                        r.xack(stream, group, msg_id)
                        record_consume_success(corr)

                    except Exception as inner:
                        # No ACK -> reintento posterior si fue fallo crítico
                        record_consume_failure(inner, payload.get("correlation_id") if 'payload' in locals() else None)

        except Exception as outer:
            record_consume_failure(outer)
            time.sleep(0.5)  # pequeño backoff ante errores de Redis

# ---- FastAPI app ----
app = FastAPI(title=SERVICE_NAME, version="1.0.0")

# Inicializa logger y pásalo al middleware que lo requiere
logger = init_logging(service_name=SERVICE_NAME)

# Middlewares de observabilidad
app.add_middleware(CorrelationIdASGIMiddleware, header_name="x-correlation-id")
app.add_middleware(RequestLoggingASGIMiddleware, logger=logger)

# CORS para pruebas
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Arranque del consumer en background (thread, por cliente Redis sync)
_consumer_thread: Optional[threading.Thread] = None

@app.on_event("startup")
def on_startup():
    global _consumer_thread
    if _consumer_thread is None or not _consumer_thread.is_alive():
        _consumer_thread = threading.Thread(target=_consumer_loop, name="notif-consumer", daemon=True)
        _consumer_thread.start()

# Endpoints
@app.get("/notifications")
def list_notifications():
    return list(NOTIFICATIONS)

@app.get("/resilience")
def resilience_snapshot():
    return {
        "service": SERVICE_NAME,
        "redis_stream_in": STREAM_IN,
        "snapshot": get_snapshot(),
    }

@app.get("/diag")
def diag():
    r = get_client()
    redis_ok, redis_err = True, None
    try:
        r.ping()
    except Exception as e:
        redis_ok, redis_err = False, str(e)

    payment_ok, payment_err = True, None
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(PAYMENT_HEALTH_URL)
            payment_ok = resp.status_code == 200
            if not payment_ok:
                payment_err = f"status={resp.status_code}"
    except Exception as e:
        payment_ok, payment_err = False, str(e)

    return {
        "service": SERVICE_NAME,
        "dependencies": {
            "redis_ok": redis_ok, "redis_error": redis_err,
            "payment_ok": payment_ok, "payment_error": payment_err,
            "payment_health_url": PAYMENT_HEALTH_URL,
        },
        "snapshot": get_snapshot(),
    }

@app.get("/health")
def health():
    return {"status": "healthy", "service": SERVICE_NAME}

@app.get("/live")
def live():
    return {"ok": True, "service": SERVICE_NAME}
