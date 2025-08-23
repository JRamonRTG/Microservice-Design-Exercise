import os
import pyodbc
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

# Cargar variables del .env
load_dotenv()

print("📂 Variables de entorno cargadas:", os.environ.keys())
print("🔌 DATABASE_URL:", os.getenv("DATABASE_URL"))


app = FastAPI(title="User Service")

# Cadena de conexión desde .env
DATABASE_URL = os.getenv("DATABASE_URL")

# Modelo para requests
class UserRequest(BaseModel):
    name: str
    email: str

class PlanRequest(BaseModel):
    plan_name: str

# 🔹 Función auxiliar para conectarse a SQL Server
def get_connection():
    print("🔌 Cadena de conexión:", DATABASE_URL)
    return pyodbc.connect(DATABASE_URL)

# Crear tablas si no existen
def init_db():
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
    conn.close()

@app.on_event("startup")
def startup_event():
    init_db()

# 🔹 Registrar usuario
@app.post("/users/register")
def register_user(req: UserRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (name, email) OUTPUT INSERTED.id VALUES (?, ?)", req.name, req.email)
    user_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return {"id": user_id, "name": req.name, "email": req.email}

# 🔹 Seleccionar plan
@app.post("/users/{user_id}/select-plan")
def select_plan(user_id: int, req: PlanRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO plans (user_id, plan_name) OUTPUT INSERTED.id VALUES (?, ?)", user_id, req.plan_name)
    plan_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return {"id": plan_id, "user_id": user_id, "plan_name": req.plan_name}
