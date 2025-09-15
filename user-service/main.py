import os
import json
import pyodbc
import redis
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Deque, Dict, Any

from observability import (
    init_logging, CorrelationIdMiddleware, RequestLoggingMiddleware,
    get_correlation_id
)

load_dotenv()

logger = init_logging("user-service")
app = FastAPI(title="User Service")

# ========= Env =========
DATABASE_URL = os.getenv("DATABASE_URL")  # ODBC connection string
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"

# Timeouts (ajustables por env)
DB_LOGIN_TIMEOUT_S = int(os.getenv("DB_LOGIN_TIMEOUT_S", "2"))        # login a SQL Server
DB_STMT_TIMEOUT_S  = int(os.getenv("DB_STMT_TIMEOUT_S", "2"))         # por statement (pyodbc)
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "2000"))     # lock timeout en SQL Server

REDIS_CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2"))
REDIS_SOCKET_TIMEOUT  = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))

# Para /diag (opcional, no rompe nada si no está running)
PAYMENT_HEALTH_URL   = os.getenv("PAYMENT_HEALTH_URL", "http://payment-service:8002/health")
PAYMENT_HTTP_TIMEOUT = float(os.getenv("PAYMENT_HTTP_TIMEOUT", "2"))

# ========= Middlewares (correlación + request logs) =========
app.add_middleware(CorrelationIdMiddleware, header_name="x-correlation-id")
app.add_middleware(RequestLoggingMiddleware, logger=logger)

# ========= Redis (lazy con timeouts) =========
_r = None
def r():
    global _r
    if _r is None:
        _r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            ssl=REDIS_SSL,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            retry_on_timeout=True,
        )
    return _r

# ========= DB helpers (con timeouts) =========
def _ensure_login_timeout(conn_str: str, seconds: int) -> str:
    """
    Si el connection string no trae LoginTimeout, lo añadimos.
    En local añadimos TrustServerCertificate=yes para evitar problemas TLS.
    """
    low = conn_str.lower()
    # LoginTimeout
    if "logintimeout=" not in low and "login timeout=" not in low:
        if not conn_str.endswith(";"):
            conn_str += ";"
        conn_str += f"Login Timeout={max(1, seconds)};"
    # TrustServerCertificate para entornos locales/contenedores
    if "trustservercertificate=" not in low:
        conn_str += "TrustServerCertificate=yes;"
    return conn_str

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurado")
    conn_str = _ensure_login_timeout(DATABASE_URL, DB_LOGIN_TIMEOUT_S)
    conn = pyodbc.connect(conn_str, autocommit=False)
    # Límite por statement (segundos)
    try:
        conn.timeout = DB_STMT_TIMEOUT_S
    except Exception:
        pass
    # Límite por locks (ms)
    try:
        with conn.cursor() as c:
            c.execute(f"SET LOCK_TIMEOUT {DB_LOCK_TIMEOUT_MS}")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        IF OBJECT_ID('dbo.users','U') IS NULL
        CREATE TABLE dbo.users(
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(200) NOT NULL,
            email NVARCHAR(200) UNIQUE NOT NULL,
            password NVARCHAR(200) NOT NULL
        );
    """)
    cur.execute("""
        IF OBJECT_ID('dbo.plans','U') IS NULL
        CREATE TABLE dbo.plans(
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            plan_id INT NOT NULL,
            plan_name NVARCHAR(200) NOT NULL,
            created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
            FOREIGN KEY (user_id) REFERENCES dbo.users(id)
        );
    """)
    conn.commit()
    cur.close(); conn.close()

try:
    init_db()
except Exception as e:
    logger.error(f"init_db error: {e}", exc_info=True)

# ========= Esquemas =========
class RegisterReq(BaseModel):
    name: str
    email: str
    password: str

class PlanReq(BaseModel):
    plan_id: int
    plan_name: str | None = None

PLANS_INFO = {1: "Plan Básico", 2: "Plan Estándar", 3: "Plan Premium"}

# ========= Resiliencia in-memory (publicación de eventos) =========
class _Resilience:
    def __init__(self, max_events: int = 100):
        self.publish_success = 0
        self.publish_fail = 0
        self.consecutive_failures = 0
        self.last_success: Optional[str] = None
        self.last_error: Optional[Dict[str, Any]] = None
        self.recent: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def ok(self, cid: Optional[str]):
        ts = self._now()
        self.publish_success += 1
        self.consecutive_failures = 0
        self.last_success = ts
        self.recent.append({"ts": ts, "type": "publish_success", "correlation_id": cid})

    def fail(self, err: str, cid: Optional[str]):
        ts = self._now()
        self.publish_fail += 1
        self.consecutive_failures += 1
        self.last_error = {"ts": ts, "error": err}
        self.recent.append({"ts": ts, "type": "publish_failure", "error": err, "correlation_id": cid})

    def snapshot(self) -> Dict[str, Any]:
        return {
            "publish_success": self.publish_success,
            "publish_fail": self.publish_fail,
            "consecutive_failures": self.consecutive_failures,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "recent": list(self.recent),
        }

_res = _Resilience()

# ========= Publicación de eventos (tolerante a fallos) =========
def publish_user_event(event: dict):
    cid = get_correlation_id()  # del middleware/ctx
    payload = {**event, "correlation_id": cid}
    try:
        r().xadd("user_events", {"data": json.dumps(payload, ensure_ascii=False)})
        logger.info(
            "Published to user_events",
            extra={"extra": {"event": "publish", "stream": "user_events", "payload": payload}},
        )
        _res.ok(cid)
    except Exception as e:
        # No tumbamos el request: solo registramos
        logger.warning(
            f"publish_user_event failed: {e}",
            extra={"extra": {"event": "publish_failure", "stream": "user_events", "error": str(e), "payload": payload}},
        )
        _res.fail(str(e), cid)

# ========= API =========
@app.post("/users/register")
def register_user(req: RegisterReq, request: Request):
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO dbo.users (name, email, password) OUTPUT INSERTED.id VALUES (?, ?, ?)",
                (req.name, req.email, req.password)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
        except pyodbc.IntegrityError:
            cur.execute("SELECT id FROM dbo.users WHERE email = ?", (req.email,))
            row = cur.fetchone()
            if not row:
                raise
            user_id = row[0]
        logger.info(
            "User registered",
            extra={"extra": {"event": "UserRegistered", "user_id": user_id, "email": req.email}},
        )
        # Evento opcional de "UserRegistered" (tolerante)
        publish_user_event({"event": "UserRegistered", "user_id": user_id})
        return {"id": user_id, "name": req.name, "email": req.email}
    except Exception as e:
        logger.error(f"/users/register error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            cur and cur.close()
            conn and conn.close()
        except Exception:
            pass

@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, req: PlanReq, request: Request):
    conn = None
    cur = None
    try:
        plan_name = req.plan_name or PLANS_INFO.get(req.plan_id, "Desconocido")
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.plans (user_id, plan_id, plan_name) VALUES (?, ?, ?)",
            (user_id, req.plan_id, plan_name)
        )
        conn.commit()
        logger.info(
            "Plan selected",
            extra={"extra": {"event": "PlanSelected", "user_id": user_id, "plan_id": req.plan_id, "plan_name": plan_name}},
        )
        # Evento para Payment (tolerante)
        publish_user_event({
            "event": "PlanSelected",
            "user_id": user_id,
            "plan_id": req.plan_id,
            "plan_name": plan_name
        })
        return {"ok": True, "user_id": user_id, "plan_id": req.plan_id, "plan_name": plan_name}
    except Exception as e:
        logger.error(f"/users/{user_id}/select-plan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            cur and cur.close()
            conn and conn.close()
        except Exception:
            pass

@app.get("/health")
def health():
    try:
        conn = get_connection(); conn.close()
        r().ping()
        return {"status": "healthy", "service": "user-service"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

# ========= Endpoints de resiliencia/diagnóstico =========
@app.get("/resilience")
def resilience():
    return {"service": "user-service", "user_stream_out": "user_events", "snapshot": _res.snapshot()}

@app.get("/diag")
async def diag():
    # DB
    db_ok, db_err = True, None
    try:
        conn = get_connection()
        with conn.cursor() as c:
            c.execute("SELECT 1")
        conn.close()
    except Exception as e:
        db_ok, db_err = False, str(e)

    # Redis
    redis_ok, redis_err = True, None
    try:
        r().ping()
    except Exception as e:
        redis_ok, redis_err = False, str(e)

    # Payment health (HTTP con timeout 2s)
    payment_ok, payment_err = True, None
    try:
        async with httpx.AsyncClient(timeout=PAYMENT_HTTP_TIMEOUT) as client:
            resp = await client.get(PAYMENT_HEALTH_URL)
            payment_ok = (resp.status_code == 200)
            if not payment_ok:
                payment_err = f"status={resp.status_code}, body={resp.text[:200]}"
    except Exception as e:
        payment_ok, payment_err = False, str(e)

    return {
        "service": "user-service",
        "dependencies": {
            "db_ok": db_ok, "db_error": db_err,
            "redis_ok": redis_ok, "redis_error": redis_err,
            "payment_ok": payment_ok, "payment_error": payment_err,
            "payment_health_url": PAYMENT_HEALTH_URL,
        },
        "snapshot": _res.snapshot(),
    }
