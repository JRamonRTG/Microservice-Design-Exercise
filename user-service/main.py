import os
import json
import pyodbc
import redis
import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
from datetime import datetime, timezone, timedelta
from collections import deque
from typing import Optional, Deque, Dict, Any

from observability import (
    init_logging, CorrelationIdMiddleware, RequestLoggingMiddleware,
    JwtUserMiddleware, get_correlation_id
)

load_dotenv()

logger = init_logging("user-service")
app = FastAPI(title="User Service")

# Middlewares
app.add_middleware(CorrelationIdMiddleware, header_name="x-correlation-id")
app.add_middleware(JwtUserMiddleware)               # <-- lee Authorization y pone user_id en logs
app.add_middleware(RequestLoggingMiddleware, logger=logger)

# --- ENV (DB/Redis ya configurados previamente) ---
DATABASE_URL = os.getenv("DATABASE_URL")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"
USER_STREAM = os.getenv("USER_STREAM", "user_events")

# Timeouts (ya añadidos en resiliencia)
DB_LOGIN_TIMEOUT_S = int(os.getenv("DB_LOGIN_TIMEOUT_S", "2"))
DB_STMT_TIMEOUT_S  = int(os.getenv("DB_STMT_TIMEOUT_S", "2"))
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "2000"))

REDIS_CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2"))
REDIS_SOCKET_TIMEOUT  = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))

# JWT
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_EXPIRES_MIN = int(os.getenv("JWT_EXPIRES_MIN", "60"))
JWT_PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH")
JWT_PUBLIC_KEY_PATH  = os.getenv("JWT_PUBLIC_KEY_PATH")
JWT_NOTIFY_ON_LOGIN = os.getenv("JWT_NOTIFY_ON_LOGIN", "false").lower() == "true"

_private_key = None
if JWT_ALG.startswith("RS") and JWT_PRIVATE_KEY_PATH and os.path.exists(JWT_PRIVATE_KEY_PATH):
    with open(JWT_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
        _private_key = f.read()

# /diag hacia payment
PAYMENT_HEALTH_URL   = os.getenv("PAYMENT_HEALTH_URL", "http://payment-service:8002/health")
PAYMENT_HTTP_TIMEOUT = float(os.getenv("PAYMENT_HTTP_TIMEOUT", "2"))

# --- Redis (con timeouts) ---
_r = None
def r():
    global _r
    if _r is None:
        _r = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            ssl=REDIS_SSL, decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            retry_on_timeout=True,
        )
    return _r

# --- DB helpers (con timeouts) ---
def _ensure_login_timeout(conn_str: str, seconds: int) -> str:
    low = conn_str.lower()
    if "logintimeout=" not in low and "login timeout=" not in low:
        if not conn_str.endswith(";"):
            conn_str += ";"
        conn_str += f"Login Timeout={max(1, seconds)};"
    if "trustservercertificate=" not in low:
        conn_str += "TrustServerCertificate=yes;"
    return conn_str

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurado")
    conn_str = _ensure_login_timeout(DATABASE_URL, DB_LOGIN_TIMEOUT_S)
    conn = pyodbc.connect(conn_str, autocommit=False)
    try:
        conn.timeout = DB_STMT_TIMEOUT_S
    except Exception:
        pass
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

# --- Esquemas ---
class RegisterReq(BaseModel):
    name: str
    email: str
    password: str

class PlanReq(BaseModel):
    plan_id: int
    plan_name: str | None = None

class LoginReq(BaseModel):
    email: str
    password: str

PLANS_INFO = {1: "Plan Básico", 2: "Plan Estándar", 3: "Plan Premium"}

# --- Resiliencia tablero (publicaciones) ---
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

def publish_user_event(event: dict):
    cid = get_correlation_id()
    payload = {**event, "correlation_id": cid}
    try:
        r().xadd("user_events", {"data": json.dumps(payload, ensure_ascii=False)})
        logger.info("publish_user_event", extra={"extra": {"event": "publish", "stream": "user_events", "target_user_id": event.get("user_id"), "payload": payload}})
        _res.ok(cid)
    except Exception as e:
        logger.warning("publish_user_event_failed", extra={"extra": {"event":"publish_failure","error":str(e),"payload":payload}})
        _res.fail(str(e), cid)

# --- JWT helpers ---
def _jwt_sign(payload: dict) -> str:
    alg = JWT_ALG.upper()
    if alg.startswith("RS"):
        if not _private_key:
            raise RuntimeError("JWT_PRIVATE_KEY_PATH no configurado para RS*")
        return jwt.encode(payload, _private_key, algorithm=alg)
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET no configurado")
    return jwt.encode(payload, JWT_SECRET, algorithm=alg)

def _issue_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=JWT_EXPIRES_MIN)
    claims = {
        "iss": "fitflow-user-service",
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": os.urandom(8).hex(),
    }
    return _jwt_sign(claims)

# --- API ---
@app.post("/users/register")
def register_user(req: RegisterReq, request: Request):
    conn = None; cur = None
    try:
        conn = get_connection(); cur = conn.cursor()
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
            if not row: raise
            user_id = row[0]
        logger.info("user_registered", extra={"extra":{"event":"UserRegistered","target_user_id":user_id,"email":req.email}})
        publish_user_event({"event":"UserRegistered","user_id":user_id})
        return {"id": user_id, "name": req.name, "email": req.email}
    except Exception as e:
        logger.error(f"/users/register error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: cur and cur.close(); conn and conn.close()
        except Exception: pass

@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, req: PlanReq, request: Request):
    plan_name = req.plan_name or PLANS_INFO.get(req.plan_id, f"Plan {req.plan_id}")
    conn = None; cur = None
    try:
        conn = get_connection(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.plans (user_id, plan_id, plan_name) VALUES (?, ?, ?)",
            (user_id, req.plan_id, plan_name)
        )
        conn.commit()
        logger.info("plan_selected", extra={"extra":{"event":"PlanSelected","target_user_id":user_id,"plan_id":req.plan_id,"plan_name":plan_name}})
        publish_user_event({"event":"PlanSelected","user_id":user_id,"plan_id":req.plan_id,"plan_name":plan_name})
        return {"ok": True, "user_id": user_id, "plan_id": req.plan_id, "plan_name": plan_name}
    except Exception as e:
        logger.error(f"/users/{user_id}/select-plan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: cur and cur.close(); conn and conn.close()
        except Exception: pass

# === NUEVO: LOGIN => genera JWT firmado ===
@app.post("/login")
def login(req: LoginReq, request: Request):
    conn = None; cur = None
    try:
        conn = get_connection(); cur = conn.cursor()
        cur.execute("SELECT id, password FROM dbo.users WHERE email = ?", (req.email,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")
        user_id, stored_password = int(row[0]), row[1]
        # NOTA: tus passwords están en texto claro actualmente; no cambiamos eso para no romper el flujo.
        if stored_password != req.password:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        token = _issue_token(user_id, req.email)
        logger.info("user_logged_in", extra={"extra":{"event":"UserLoggedIn","user_id":user_id}})

        # Evento opcional (para demo) con el token en el payload -> Notification podría notificarlo
        if JWT_NOTIFY_ON_LOGIN:
            publish_user_event({"event":"UserLoggedIn","user_id":user_id,"email":req.email,"jwt":token})

        return {"access_token": token, "token_type": "Bearer", "expires_in_minutes": JWT_EXPIRES_MIN}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: cur and cur.close(); conn and conn.close()
        except Exception: pass

@app.get("/health")
def health():
    try:
        conn = get_connection(); conn.close()
        r().ping()
        return {"status": "healthy", "service": "user-service"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/resilience")
def resilience():
    return {"service":"user-service","user_stream_out":"user_events","snapshot":_res.snapshot()}

@app.get("/diag")
async def diag():
    # DB
    db_ok, db_err = True, None
    try:
        conn = get_connection()
        with conn.cursor() as c: c.execute("SELECT 1")
        conn.close()
    except Exception as e:
        db_ok, db_err = False, str(e)
    # Redis
    redis_ok, redis_err = True, None
    try:
        r().ping()
    except Exception as e:
        redis_ok, redis_err = False, str(e)
    # Payment
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
        "service":"user-service",
        "dependencies":{
            "db_ok":db_ok,"db_error":db_err,
            "redis_ok":redis_ok,"redis_error":redis_err,
            "payment_ok":payment_ok,"payment_error":payment_err,
            "payment_health_url":PAYMENT_HEALTH_URL
        },
        "snapshot":_res.snapshot()
    }
