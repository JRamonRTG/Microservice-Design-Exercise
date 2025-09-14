import os
import json
import pyodbc
import redis
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv

from observability import (
    init_logging, CorrelationIdMiddleware, RequestLoggingMiddleware,
    get_correlation_id
)

load_dotenv()

logger = init_logging("user-service")

app = FastAPI(title="User Service")

# Env
DATABASE_URL = os.getenv("DATABASE_URL")  # ODBC connection string
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"

# Middlewares (correlación + request logs)
app.add_middleware(CorrelationIdMiddleware, header_name="x-correlation-id")
app.add_middleware(RequestLoggingMiddleware, logger=logger)

# Redis (lazy)
_r = None
def r():
    global _r
    if _r is None:
        _r = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT,
            password=REDIS_PASSWORD, ssl=REDIS_SSL,
            decode_responses=True
        )
    return _r

# DB helpers
def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurado")
    return pyodbc.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        IF OBJECT_ID('dbo.users','U') IS NULL
        CREATE TABLE dbo.users(
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(200) NOT NULL,
            email NVARCHAR(200) NOT NULL UNIQUE,
            password NVARCHAR(200) NOT NULL
        );
    """)
    conn.commit()
    cur.execute("""
        IF OBJECT_ID('dbo.plans','U') IS NULL
        CREATE TABLE dbo.plans(
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            plan_id INT NOT NULL,
            plan_name NVARCHAR(100) NOT NULL,
            created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_plans_users FOREIGN KEY (user_id) REFERENCES dbo.users(id)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("DB initialized")

@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception as e:
        logger.error(f"init_db error: {e}", exc_info=True)

# Schemas
class RegisterReq(BaseModel):
    name: str
    email: str
    password: str

class PlanReq(BaseModel):
    plan_id: int
    plan_name: str | None = None

PLANS_INFO = {1: "Plan Básico", 2: "Plan Estándar", 3: "Plan Premium"}

def publish_user_event(event: dict):
    cid = get_correlation_id()  # del middleware/ctx
    payload = {**event, "correlation_id": cid}
    r().xadd("user_events", {"data": json.dumps(payload)})
    logger.info(
        "Published to user_events",
        extra={"extra": {"event": "publish", "stream": "user_events", "payload": payload}},
    )

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
        # Evento opcional de "UserRegistered"
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
        # Evento para Payment
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
