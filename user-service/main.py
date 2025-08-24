import os
import pyodbc
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import redis
import json

# Cargar variables de entorno en local
load_dotenv()

app = FastAPI(title="User Service")

# Variables de entorno
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

print("📂 DATABASE_URL:", DATABASE_URL)
print("🔁 REDIS_HOST:", REDIS_HOST)

# Modelos
class UserRequest(BaseModel):
    name: str
    email: str

class PlanRequest(BaseModel):
    plan_name: str

# Conexión a SQL Server
def get_connection():
    try:
        print("📡 Intentando conexión a SQL Server...")
        conn = pyodbc.connect(DATABASE_URL)
        print("✅ Conexión a SQL Server exitosa")
        return conn
    except Exception as e:
        print("❌ Error al conectar a SQL Server:", e)
        raise HTTPException(status_code=500, detail=f"DB Error: {e}")

# Conexión a Redis
def get_redis_client():
    try:
        print("🔗 Conectando a Redis...")
        r = redis.Redis(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            password=REDIS_PASSWORD,
            decode_responses=True,
            ssl=True
        )
        r.ping()
        print("✅ Conexión a Redis exitosa")
        return r
    except Exception as e:
        print("❌ Redis no disponible:", e)
        return None

# Inicializar DB
def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' and xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(100) NOT NULL,
            email NVARCHAR(100) UNIQUE NOT NULL
        )
        """)

        cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='plans' and xtype='U')
        CREATE TABLE plans (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            plan_name NVARCHAR(50) NOT NULL
        )
        """)

        conn.commit()
        print("📦 Tablas verificadas/creadas")
    except Exception as e:
        print("❌ Error al inicializar base de datos:", e)
    finally:
        try: cursor.close()
        except: pass
        try: conn.close()
        except: pass

@app.on_event("startup")
def startup_event():
    init_db()

# Endpoint: registro de usuario
@app.post("/users/register")
def register_user(req: UserRequest):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, email) OUTPUT INSERTED.id VALUES (?, ?)", req.name, req.email)
        user_id = cursor.fetchone()[0]
        conn.commit()
        print(f"✅ Usuario registrado: ID={user_id}")

        # Emitir evento a Redis
        r = get_redis_client()
        if r:
            r.xadd("user_events", {"data": "primero"})
            print("📨 Evento UserRegistered enviado")

        return {"id": user_id, "name": req.name, "email": req.email}
    except Exception as e:
        print("❌ Error en /users/register:", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

# Endpoint: selección de plan
@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, req: PlanRequest):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO plans (user_id, plan_name) OUTPUT INSERTED.id VALUES (?, ?)", user_id, req.plan_name)
        plan_id = cursor.fetchone()[0]
        conn.commit()
        print(f"✅ Plan registrado: ID={plan_id}")

        # Emitir evento a Redis
        r = get_redis_client()
        if r:
            event = json.dumps({"event": "PlanSelected", "plan_id": plan_id, "user_id": user_id, "plan_name": req.plan_name})
            r.xadd("user_events", {"data": event})
            print("📨 Evento PlanSelected enviado")

        return {"id": plan_id, "user_id": user_id, "plan_name": req.plan_name}
    except Exception as e:
        print("❌ Error en /users/{user_id}/select-plan:", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass